package launcher

import (
	"context"
	"crypto/rand"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"net"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"time"
)

type SystemPlatform struct{}

func (SystemPlatform) Detect(ctx context.Context) (OpenCodeInfo, error) {
	candidates := opencodeCandidates()
	seen := make(map[string]bool)
	for _, candidate := range candidates {
		if candidate == "" {
			continue
		}
		canonical, err := filepath.EvalSymlinks(candidate)
		if err != nil || seen[canonical] {
			continue
		}
		seen[canonical] = true
		info, err := os.Stat(canonical)
		if err != nil || !info.Mode().IsRegular() || info.Mode().Perm()&0111 == 0 {
			continue
		}
		versionCtx, cancel := context.WithTimeout(ctx, 3*time.Second)
		output, err := exec.CommandContext(versionCtx, canonical, "--version").CombinedOutput()
		cancel()
		if err != nil {
			continue
		}
		version := strings.TrimSpace(string(output))
		if len(version) > 128 {
			version = version[:128]
		}
		return OpenCodeInfo{Executable: canonical, Version: version}, nil
	}
	return OpenCodeInfo{}, fmt.Errorf("OpenCode executable was not found in supported install locations")
}

func opencodeCandidates() []string {
	home, _ := os.UserHomeDir()
	candidates := []string{
		filepath.Join(home, ".opencode", "bin", "opencode"),
		filepath.Join(home, ".local", "bin", "opencode"),
		"/opt/homebrew/bin/opencode",
		"/usr/local/bin/opencode",
	}
	if path, err := exec.LookPath("opencode"); err == nil {
		candidates = append([]string{path}, candidates...)
	}
	return candidates
}

func (SystemPlatform) SelectDirectory(ctx context.Context, initial string) (string, bool, error) {
	selected, ok, err := selectDirectory(ctx, initial, "选择 OpenCode 项目文件夹")
	if err != nil || !ok {
		return "", ok, err
	}
	canonical, err := canonicalWorkspace(selected)
	if err != nil {
		return "", false, err
	}
	return canonical, true, nil
}

func (SystemPlatform) CreateDirectory(ctx context.Context, initial, name string) (string, bool, error) {
	name = strings.TrimSpace(name)
	if name == "" || name == "." || name == ".." || filepath.Base(name) != name || strings.ContainsAny(name, "\x00\r\n") {
		return "", false, CodedError{Code: "DIRECTORY_NAME_INVALID", Message: "directory name is invalid"}
	}
	parent, selected, err := selectDirectory(ctx, initial, "选择新项目的父文件夹")
	if err != nil || !selected {
		return "", selected, err
	}
	parent, err = canonicalWorkspace(parent)
	if err != nil {
		return "", false, err
	}
	workspace := filepath.Join(parent, name)
	if _, err := os.Stat(workspace); err == nil {
		return "", false, CodedError{Code: "DIRECTORY_EXISTS", Message: "a file or directory with the same name already exists"}
	} else if !os.IsNotExist(err) {
		return "", false, CodedError{Code: "DIRECTORY_CREATE_FAILED", Message: "directory cannot be inspected"}
	}
	if err := os.Mkdir(workspace, 0755); err != nil {
		return "", false, CodedError{Code: "DIRECTORY_CREATE_FAILED", Message: "directory could not be created"}
	}
	canonical, err := canonicalWorkspace(workspace)
	if err != nil {
		return "", false, err
	}
	return canonical, true, nil
}

func canonicalWorkspace(workspace string) (string, error) {
	if workspace == "" || !filepath.IsAbs(workspace) {
		return "", CodedError{Code: "WORKSPACE_INVALID", Message: "workspace must be an absolute directory"}
	}
	canonical, err := filepath.EvalSymlinks(workspace)
	if err != nil {
		return "", CodedError{Code: "WORKSPACE_INVALID", Message: "workspace does not exist or cannot be accessed"}
	}
	info, err := os.Stat(canonical)
	if err != nil || !info.IsDir() {
		return "", CodedError{Code: "WORKSPACE_INVALID", Message: "workspace is not a directory"}
	}
	return canonical, nil
}

func validateCredential(value, name string, maxLength int) error {
	if len(value) > maxLength || strings.ContainsAny(value, "\x00\r\n") {
		return CodedError{Code: "INVALID_REQUEST", Message: name + " is invalid"}
	}
	return nil
}

func generatePassword() (string, error) {
	buffer := make([]byte, 32)
	if _, err := rand.Read(buffer); err != nil {
		return "", err
	}
	return base64.RawURLEncoding.EncodeToString(buffer), nil
}

func portAvailable(port int) bool {
	listener, err := net.Listen("tcp", fmt.Sprintf("127.0.0.1:%d", port))
	if err != nil {
		return false
	}
	_ = listener.Close()
	return true
}

type endpointState int

const (
	endpointUnavailable endpointState = iota
	endpointHealthy
	endpointAuthMismatch
)

func inspectOpenCodeEndpoint(port int, username, password string) endpointState {
	client := &http.Client{Timeout: 700 * time.Millisecond}
	request, _ := http.NewRequest(http.MethodGet, fmt.Sprintf("http://127.0.0.1:%d/global/health", port), nil)
	if password != "" {
		request.SetBasicAuth(username, password)
	}
	response, err := client.Do(request)
	if err != nil {
		return endpointUnavailable
	}
	defer response.Body.Close()
	if response.StatusCode == http.StatusUnauthorized || response.StatusCode == http.StatusForbidden {
		return endpointAuthMismatch
	}
	if response.StatusCode < 200 || response.StatusCode >= 300 {
		return endpointUnavailable
	}
	var health struct {
		Healthy bool `json:"healthy"`
	}
	if err := json.NewDecoder(response.Body).Decode(&health); err != nil || !health.Healthy {
		return endpointUnavailable
	}
	return endpointHealthy
}

func choosePort(preferred int, allowFallback bool, username, password string) (int, bool, error) {
	if preferred < 1024 || preferred > 65535 {
		return 0, false, CodedError{Code: "INVALID_REQUEST", Message: "preferred port is outside the allowed range"}
	}
	switch inspectOpenCodeEndpoint(preferred, username, password) {
	case endpointHealthy:
		return preferred, true, nil
	case endpointAuthMismatch:
		if !allowFallback {
			return 0, false, CodedError{Code: "AUTH_MISMATCH", Message: "an OpenCode server is running but its credentials do not match"}
		}
	}
	if portAvailable(preferred) {
		return preferred, false, nil
	}
	if allowFallback {
		limit := preferred + 9
		if limit > 65535 {
			limit = 65535
		}
		for port := preferred + 1; port <= limit; port++ {
			if portAvailable(port) {
				return port, false, nil
			}
		}
	}
	return 0, false, CodedError{Code: "PORT_IN_USE", Message: "preferred OpenCode port is already in use"}
}

func (platform SystemPlatform) Launch(ctx context.Context, input LaunchInput) (LaunchResult, error) {
	workspace, err := canonicalWorkspace(input.Workspace)
	if err != nil {
		return LaunchResult{}, err
	}
	username := input.Username
	if username == "" {
		username = "opencode"
	}
	if err := validateCredential(username, "username", 128); err != nil {
		return LaunchResult{}, err
	}
	if err := validateCredential(input.Password, "password", 1024); err != nil {
		return LaunchResult{}, err
	}

	port, alreadyRunning, err := choosePort(input.PreferredPort, input.AllowPortFallback, username, input.Password)
	if err != nil {
		return LaunchResult{}, err
	}
	endpoint := fmt.Sprintf("http://127.0.0.1:%d", port)
	if alreadyRunning {
		return LaunchResult{
			Status: "already_running", Endpoint: endpoint, Workspace: workspace,
			Username: username, Password: input.Password,
		}, nil
	}

	info, err := platform.Detect(ctx)
	if err != nil {
		return LaunchResult{}, CodedError{Code: "OPENCODE_NOT_FOUND", Message: err.Error()}
	}
	password := input.Password
	if password == "" {
		password, err = generatePassword()
		if err != nil {
			return LaunchResult{}, CodedError{Code: "SPAWN_FAILED", Message: "could not generate server credentials"}
		}
	}

	logDirectory, err := launcherLogDirectory()
	if err != nil {
		return LaunchResult{}, CodedError{Code: "SPAWN_FAILED", Message: "could not create launcher log directory"}
	}
	logPath := filepath.Join(logDirectory, fmt.Sprintf("opencode-%d.log", port))
	logFile, err := os.OpenFile(logPath, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0600)
	if err != nil {
		return LaunchResult{}, CodedError{Code: "SPAWN_FAILED", Message: "could not open OpenCode log file"}
	}

	command := exec.Command(info.Executable, "serve", "--hostname", "127.0.0.1", "--port", fmt.Sprint(port))
	command.Dir = workspace
	command.Env = append(os.Environ(),
		"OPENCODE_SERVER_USERNAME="+username,
		"OPENCODE_SERVER_PASSWORD="+password,
	)
	command.Stdin = nil
	command.Stdout = logFile
	command.Stderr = logFile
	detachCommand(command)
	if err := command.Start(); err != nil {
		_ = logFile.Close()
		return LaunchResult{}, CodedError{Code: "SPAWN_FAILED", Message: "the operating system refused to start OpenCode"}
	}
	pid := command.Process.Pid
	_ = command.Process.Release()
	_ = logFile.Close()

	return LaunchResult{
		Status: "started", PID: pid, Endpoint: endpoint, Workspace: workspace,
		Username: username, Password: password, Version: info.Version, LogPath: logPath,
	}, nil
}

func launcherLogDirectory() (string, error) {
	home, err := os.UserHomeDir()
	if err != nil {
		return "", err
	}
	directory := filepath.Join(home, "Library", "Logs", "Eido")
	if err := os.MkdirAll(directory, 0700); err != nil {
		return "", err
	}
	return directory, nil
}
