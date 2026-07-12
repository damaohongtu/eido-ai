//go:build darwin || linux

package launcher

import (
	"os/exec"
	"syscall"
)

func detachCommand(command *exec.Cmd) {
	command.SysProcAttr = &syscall.SysProcAttr{Setsid: true}
}
