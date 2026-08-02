//go:build windows

package launcher

import (
	"errors"
	"fmt"
	"os"
	"os/exec"
	"syscall"
)

const (
	createNewProcessGroup  = 0x00000200
	detachedProcess        = 0x00000008
	createBreakawayFromJob = 0x01000000
)

func windowsOpenCodeCommand(input openCodeProcessInput, logFile *os.File, flags uint32) *exec.Cmd {
	command := exec.Command(
		input.Executable,
		"serve", "--hostname", "127.0.0.1", "--port", fmt.Sprint(input.Port),
	)
	command.Dir = input.Workspace
	command.Env = replaceWindowsEnvironment(os.Environ(), map[string]string{
		"OPENCODE_SERVER_USERNAME": input.Username,
		"OPENCODE_SERVER_PASSWORD": input.Password,
	})
	command.Stdin = nil
	command.Stdout = logFile
	command.Stderr = logFile
	command.SysProcAttr = &syscall.SysProcAttr{
		CreationFlags: flags,
		HideWindow:    true,
	}
	return command
}

func startOpenCodeProcess(input openCodeProcessInput) (int, error) {
	logFile, err := os.OpenFile(input.LogPath, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0600)
	if err != nil {
		return 0, err
	}
	flags := uint32(createNewProcessGroup | detachedProcess | createBreakawayFromJob)
	command := windowsOpenCodeCommand(input, logFile, flags)
	if err := command.Start(); err != nil {
		// A containing job object may disallow breakaway. Detached process-group
		// creation still prevents the child from inheriting the native host console
		// and protocol pipes, so retry without only that optional flag.
		command = windowsOpenCodeCommand(input, logFile, flags&^createBreakawayFromJob)
		if retryErr := command.Start(); retryErr != nil {
			_ = logFile.Close()
			return 0, retryErr
		}
	}
	if command.Process == nil {
		_ = logFile.Close()
		return 0, errors.New("Windows did not return an OpenCode process")
	}
	pid := command.Process.Pid
	_ = command.Process.Release()
	_ = logFile.Close()
	return pid, nil
}

func RunDetachedOpenCodeRequest(string, string) error {
	return errors.New("detached OpenCode helper mode is only supported on macOS")
}
