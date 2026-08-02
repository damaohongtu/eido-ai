//go:build linux

package launcher

import (
	"errors"
	"fmt"
	"os"
	"os/exec"
	"syscall"
)

func startOpenCodeProcess(input openCodeProcessInput) (int, error) {
	logFile, err := os.OpenFile(input.LogPath, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0600)
	if err != nil {
		return 0, err
	}
	command := exec.Command(input.Executable, "serve", "--hostname", "127.0.0.1", "--port", fmt.Sprint(input.Port))
	command.Dir = input.Workspace
	command.Env = append(os.Environ(),
		"OPENCODE_SERVER_USERNAME="+input.Username,
		"OPENCODE_SERVER_PASSWORD="+input.Password,
	)
	command.Stdin = nil
	command.Stdout = logFile
	command.Stderr = logFile
	command.SysProcAttr = &syscall.SysProcAttr{Setsid: true}
	if err := command.Start(); err != nil {
		_ = logFile.Close()
		return 0, err
	}
	pid := command.Process.Pid
	_ = command.Process.Release()
	_ = logFile.Close()
	return pid, nil
}

func RunDetachedOpenCodeRequest(string, string) error {
	return errors.New("detached OpenCode helper mode is only supported on macOS")
}
