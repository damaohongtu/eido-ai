//go:build darwin

package launcher

import (
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestLaunchRequestRoundTripUsesPrivateFile(t *testing.T) {
	directory := t.TempDir()
	want := darwinLaunchRequest{
		Executable: "/usr/local/bin/opencode",
		Workspace:  "/tmp/project",
		Username:   "opencode",
		Password:   "secret",
		Port:       4096,
	}
	path, token, err := writeLaunchRequest(directory, want)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = os.Remove(path) })
	if token == "" || !strings.HasPrefix(filepath.Base(path), "opencode-launch-") {
		t.Fatalf("unexpected launch request path %q", path)
	}
	info, err := os.Stat(path)
	if err != nil {
		t.Fatal(err)
	}
	if info.Mode().Perm() != 0600 {
		t.Fatalf("launch request permissions = %o, want 600", info.Mode().Perm())
	}
	got, err := readLaunchRequest(path, directory)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(path); !os.IsNotExist(err) {
		t.Fatalf("launch request was not consumed: %v", err)
	}
	if got != want {
		t.Fatalf("launch request = %#v, want %#v", got, want)
	}
}

func TestReadLaunchRequestRejectsPathOutsidePrivateDirectory(t *testing.T) {
	privateDirectory := t.TempDir()
	otherDirectory := t.TempDir()
	path, _, err := writeLaunchRequest(otherDirectory, darwinLaunchRequest{Port: 4096})
	if err != nil {
		t.Fatal(err)
	}
	if _, err := readLaunchRequest(path, privateDirectory); err == nil {
		t.Fatal("expected an out-of-directory launch request to be rejected")
	}
}

func TestLaunchAgentPlistIsPrivateAndEscapesArguments(t *testing.T) {
	directory := t.TempDir()
	label := "ai.eido.opencode.4096.0123456789abcdef01234567"
	path, err := writeLaunchAgentPlist(
		directory,
		label,
		"/Applications/Eido & Tools/launcher",
		filepath.Join(directory, "request.json"),
		filepath.Join(directory, "open<code>.log"),
	)
	if err != nil {
		t.Fatal(err)
	}
	info, err := os.Stat(path)
	if err != nil {
		t.Fatal(err)
	}
	if info.Mode().Perm() != 0600 {
		t.Fatalf("launch agent plist permissions = %o, want 600", info.Mode().Perm())
	}
	contents, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	text := string(contents)
	for _, expected := range []string{
		"<string>" + label + "</string>",
		"/Applications/Eido &amp; Tools/launcher",
		"open&lt;code&gt;.log",
		"<key>RunAtLoad</key>",
	} {
		if !strings.Contains(text, expected) {
			t.Fatalf("launch agent plist does not contain %q: %s", expected, text)
		}
	}
}

func TestRunDetachedOpenCodeRequestDeletesCredentialsBeforeExec(t *testing.T) {
	directory := t.TempDir()
	workspace := t.TempDir()
	executable := filepath.Join(t.TempDir(), "opencode")
	if err := os.WriteFile(executable, []byte("test executable"), 0700); err != nil {
		t.Fatal(err)
	}
	path, _, err := writeLaunchRequest(directory, darwinLaunchRequest{
		Executable: executable,
		Workspace:  workspace,
		Username:   "opencode",
		Password:   "secret",
		Port:       4103,
	})
	if err != nil {
		t.Fatal(err)
	}

	execCalled := false
	wantStop := errors.New("stop before replacing test process")
	wantExecutable, err := filepath.EvalSymlinks(executable)
	if err != nil {
		t.Fatal(err)
	}
	wantWorkspace, err := filepath.EvalSymlinks(workspace)
	if err != nil {
		t.Fatal(err)
	}
	err = runDetachedOpenCodeRequest(path, directory, func(
		gotExecutable string,
		args, environment []string,
		gotWorkspace string,
	) error {
		execCalled = true
		if _, statErr := os.Stat(path); !os.IsNotExist(statErr) {
			t.Fatalf("launch request still exists during exec: %v", statErr)
		}
		if gotExecutable != wantExecutable || gotWorkspace != wantWorkspace {
			t.Fatalf("unexpected exec target %q in %q", gotExecutable, gotWorkspace)
		}
		joinedArgs := strings.Join(args, " ")
		if !strings.Contains(joinedArgs, "serve --hostname 127.0.0.1 --port 4103") {
			t.Fatalf("unexpected OpenCode arguments: %q", joinedArgs)
		}
		joinedEnvironment := strings.Join(environment, "\n")
		if !strings.Contains(joinedEnvironment, "OPENCODE_SERVER_USERNAME=opencode") ||
			!strings.Contains(joinedEnvironment, "OPENCODE_SERVER_PASSWORD=secret") {
			t.Fatalf("OpenCode credentials missing from environment")
		}
		return wantStop
	})
	if !errors.Is(err, wantStop) || !execCalled {
		t.Fatalf("unexpected detached launch result: called=%v err=%v", execCalled, err)
	}
}

func TestProcessEnvironmentReplacesInheritedCredentials(t *testing.T) {
	t.Setenv("OPENCODE_SERVER_USERNAME", "inherited-user")
	t.Setenv("OPENCODE_SERVER_PASSWORD", "inherited-password")
	environment := processEnvironment("requested-user", "requested-password")
	joined := strings.Join(environment, "\n")
	if strings.Contains(joined, "inherited-user") || strings.Contains(joined, "inherited-password") {
		t.Fatal("inherited OpenCode credentials were not removed")
	}
	if strings.Count(joined, "OPENCODE_SERVER_USERNAME=requested-user") != 1 ||
		strings.Count(joined, "OPENCODE_SERVER_PASSWORD=requested-password") != 1 {
		t.Fatalf("requested credentials were not installed exactly once")
	}
}

func TestDetachedHelperRejectsInvalidLaunchJobLabel(t *testing.T) {
	if err := RunDetachedOpenCodeRequest("/tmp/request.json", "com.example.untrusted"); err == nil {
		t.Fatal("expected an invalid launchd label to be rejected")
	}
}
