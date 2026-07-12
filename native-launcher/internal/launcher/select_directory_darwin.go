//go:build darwin

package launcher

import (
	"context"
	"errors"
	"os/exec"
	"strings"
)

const directoryPickerScript = `on run argv
  set initialPath to item 1 of argv
  try
    if initialPath is "" then
      set selectedFolder to choose folder with prompt "选择 OpenCode 项目文件夹"
    else
      set selectedFolder to choose folder with prompt "选择 OpenCode 项目文件夹" default location POSIX file initialPath
    end if
    return POSIX path of selectedFolder
  on error number -128
    return ""
  end try
end run`

func selectDirectory(ctx context.Context, initial string) (string, bool, error) {
	command := exec.CommandContext(ctx, "/usr/bin/osascript", "-e", directoryPickerScript, initial)
	output, err := command.Output()
	if err != nil {
		return "", false, errors.New("the macOS directory selector could not be opened")
	}
	selected := strings.TrimSpace(string(output))
	return selected, selected != "", nil
}
