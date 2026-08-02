//go:build darwin

package launcher

import (
	"bytes"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"encoding/xml"
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strings"
)

const maxLaunchRequestSize = 16 * 1024

type darwinLaunchRequest struct {
	Executable string `json:"executable"`
	Workspace  string `json:"workspace"`
	Username   string `json:"username"`
	Password   string `json:"password"`
	Port       int    `json:"port"`
}

type runProcessFunc func(executable string, args, environment []string, workspace string) error

var launchLabelPattern = regexp.MustCompile(`^ai\.eido\.opencode\.[0-9]+\.[a-f0-9]{24}$`)

func launchRequestDirectory() (string, error) {
	home, err := os.UserHomeDir()
	if err != nil {
		return "", err
	}
	directory := filepath.Join(home, "Library", "Application Support", "Eido", "run")
	if err := os.MkdirAll(directory, 0700); err != nil {
		return "", err
	}
	if err := os.Chmod(directory, 0700); err != nil {
		return "", err
	}
	return directory, nil
}

func randomLaunchToken() (string, error) {
	buffer := make([]byte, 12)
	if _, err := rand.Read(buffer); err != nil {
		return "", err
	}
	return hex.EncodeToString(buffer), nil
}

func writeLaunchRequest(directory string, request darwinLaunchRequest) (string, string, error) {
	token, err := randomLaunchToken()
	if err != nil {
		return "", "", err
	}
	path := filepath.Join(directory, "opencode-launch-"+token+".json")
	file, err := os.OpenFile(path, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0600)
	if err != nil {
		return "", "", err
	}
	encoder := json.NewEncoder(file)
	encodeErr := encoder.Encode(request)
	closeErr := file.Close()
	if encodeErr != nil {
		_ = os.Remove(path)
		return "", "", encodeErr
	}
	if closeErr != nil {
		_ = os.Remove(path)
		return "", "", closeErr
	}
	return path, token, nil
}

func writePlistString(buffer *bytes.Buffer, value string) error {
	buffer.WriteString("<string>")
	if err := xml.EscapeText(buffer, []byte(value)); err != nil {
		return err
	}
	buffer.WriteString("</string>\n")
	return nil
}

func writeLaunchAgentPlist(directory, label, launcherExecutable, requestPath, logPath string) (string, error) {
	path := filepath.Join(directory, label+".plist")
	var contents bytes.Buffer
	contents.WriteString(`<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
<key>Label</key>
`)
	if err := writePlistString(&contents, label); err != nil {
		return "", err
	}
	contents.WriteString("<key>ProgramArguments</key>\n<array>\n")
	for _, argument := range []string{launcherExecutable, DetachedOpenCodeSubcommand, requestPath, label} {
		if err := writePlistString(&contents, argument); err != nil {
			return "", err
		}
	}
	contents.WriteString("</array>\n<key>StandardOutPath</key>\n")
	if err := writePlistString(&contents, logPath); err != nil {
		return "", err
	}
	contents.WriteString("<key>StandardErrorPath</key>\n")
	if err := writePlistString(&contents, logPath); err != nil {
		return "", err
	}
	contents.WriteString("<key>ProcessType</key>\n<string>Background</string>\n<key>RunAtLoad</key>\n<true/>\n</dict>\n</plist>\n")

	file, err := os.OpenFile(path, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0600)
	if err != nil {
		return "", err
	}
	_, writeErr := file.Write(contents.Bytes())
	closeErr := file.Close()
	if writeErr != nil {
		_ = os.Remove(path)
		return "", writeErr
	}
	if closeErr != nil {
		_ = os.Remove(path)
		return "", closeErr
	}
	return path, nil
}

func startOpenCodeProcess(input openCodeProcessInput) (int, error) {
	launcherExecutable, err := os.Executable()
	if err != nil {
		return 0, err
	}
	launcherExecutable, err = filepath.EvalSymlinks(launcherExecutable)
	if err != nil {
		return 0, err
	}
	directory, err := launchRequestDirectory()
	if err != nil {
		return 0, err
	}
	requestPath, token, err := writeLaunchRequest(directory, darwinLaunchRequest{
		Executable: input.Executable,
		Workspace:  input.Workspace,
		Username:   input.Username,
		Password:   input.Password,
		Port:       input.Port,
	})
	if err != nil {
		return 0, err
	}

	label := fmt.Sprintf("ai.eido.opencode.%d.%s", input.Port, token)
	plistPath, err := writeLaunchAgentPlist(
		directory, label, launcherExecutable, requestPath, input.LogPath,
	)
	if err != nil {
		_ = os.Remove(requestPath)
		return 0, err
	}
	launchDomain := fmt.Sprintf("gui/%d", os.Getuid())
	command := exec.Command(
		"/bin/launchctl", "bootstrap", launchDomain, plistPath,
	)
	if output, err := command.CombinedOutput(); err != nil {
		_ = os.Remove(requestPath)
		_ = os.Remove(plistPath)
		message := strings.TrimSpace(string(output))
		if message == "" {
			message = err.Error()
		}
		return 0, fmt.Errorf("launchctl bootstrap failed: %s", message)
	}
	_ = os.Remove(plistPath)

	// launchctl bootstrap does not expose the child PID. Readiness is confirmed by
	// the caller through OpenCode's authenticated loopback health endpoint.
	return 0, nil
}

func readLaunchRequest(path, expectedDirectory string) (darwinLaunchRequest, error) {
	var request darwinLaunchRequest
	cleanPath := filepath.Clean(path)
	if !filepath.IsAbs(cleanPath) || filepath.Dir(cleanPath) != filepath.Clean(expectedDirectory) {
		return request, errors.New("launch request path is outside the private run directory")
	}
	info, err := os.Lstat(cleanPath)
	if err != nil {
		return request, err
	}
	if !info.Mode().IsRegular() || info.Mode().Perm()&0077 != 0 || info.Size() > maxLaunchRequestSize {
		return request, errors.New("launch request file is not a private regular file")
	}
	file, err := os.Open(cleanPath)
	if err != nil {
		return request, err
	}
	if err := os.Remove(cleanPath); err != nil {
		_ = file.Close()
		return request, err
	}
	decoder := json.NewDecoder(io.LimitReader(file, maxLaunchRequestSize+1))
	decoder.DisallowUnknownFields()
	decodeErr := decoder.Decode(&request)
	closeErr := file.Close()
	if decodeErr != nil {
		return request, decodeErr
	}
	if closeErr != nil {
		return request, closeErr
	}
	return request, nil
}

func validateLaunchRequest(request darwinLaunchRequest) (darwinLaunchRequest, error) {
	if request.Port < 1024 || request.Port > 65535 {
		return request, errors.New("launch request port is outside the allowed range")
	}
	if err := validateCredential(request.Username, "username", 128); err != nil {
		return request, err
	}
	if err := validateCredential(request.Password, "password", 1024); err != nil {
		return request, err
	}
	workspace, err := canonicalWorkspace(request.Workspace)
	if err != nil {
		return request, err
	}
	executable, err := filepath.EvalSymlinks(request.Executable)
	if err != nil || !filepath.IsAbs(executable) {
		return request, errors.New("OpenCode executable is invalid")
	}
	info, err := os.Stat(executable)
	if err != nil || !info.Mode().IsRegular() || info.Mode().Perm()&0111 == 0 {
		return request, errors.New("OpenCode executable is not executable")
	}
	request.Workspace = workspace
	request.Executable = executable
	return request, nil
}

func processEnvironment(username, password string) []string {
	environment := make([]string, 0, len(os.Environ())+2)
	for _, item := range os.Environ() {
		if strings.HasPrefix(item, "OPENCODE_SERVER_USERNAME=") ||
			strings.HasPrefix(item, "OPENCODE_SERVER_PASSWORD=") {
			continue
		}
		environment = append(environment, item)
	}
	return append(environment,
		"OPENCODE_SERVER_USERNAME="+username,
		"OPENCODE_SERVER_PASSWORD="+password,
	)
}

func runOpenCodeProcess(executable string, args, environment []string, workspace string) error {
	command := exec.Command(executable, args[1:]...)
	command.Dir = workspace
	command.Env = environment
	command.Stdin = nil
	command.Stdout = os.Stdout
	command.Stderr = os.Stderr
	return command.Run()
}

func runDetachedOpenCodeRequest(
	path, expectedDirectory string,
	run runProcessFunc,
) error {
	request, err := readLaunchRequest(path, expectedDirectory)
	if err != nil {
		return err
	}
	request, err = validateLaunchRequest(request)
	if err != nil {
		return err
	}
	args := []string{
		request.Executable,
		"serve", "--hostname", "127.0.0.1", "--port", fmt.Sprint(request.Port),
	}
	return run(
		request.Executable,
		args,
		processEnvironment(request.Username, request.Password),
		request.Workspace,
	)
}

// RunDetachedOpenCodeRequest is invoked only by the launchd-bootstrapped helper
// mode of this signed launcher. The native-messaging mode never accepts paths
// or credentials for this entry point from the extension.
func removeLaunchJob(label string) {
	job := fmt.Sprintf("gui/%d/%s", os.Getuid(), label)
	command := exec.Command("/bin/launchctl", "bootout", job)
	command.Stdin = nil
	command.Stdout = nil
	command.Stderr = nil
	if err := command.Start(); err == nil {
		_ = command.Process.Release()
		return
	}
	fallback := exec.Command("/bin/launchctl", "remove", label)
	if err := fallback.Start(); err == nil {
		_ = fallback.Process.Release()
	}
}

func RunDetachedOpenCodeRequest(path, label string) error {
	if !launchLabelPattern.MatchString(label) {
		return errors.New("launchd job label is invalid")
	}
	defer removeLaunchJob(label)
	directory, err := launchRequestDirectory()
	if err != nil {
		return err
	}
	return runDetachedOpenCodeRequest(path, directory, runOpenCodeProcess)
}
