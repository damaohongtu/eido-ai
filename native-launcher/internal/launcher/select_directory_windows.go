//go:build windows

package launcher

import (
	"context"
	"encoding/base64"
	"errors"
	"os"
	"os/exec"
	"strings"
	"syscall"
	"unicode/utf16"
)

const windowsDirectoryPickerScript = `$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
Add-Type -AssemblyName System.Windows.Forms
$dialog = [System.Windows.Forms.FolderBrowserDialog]::new()
try {
  $dialog.Description = $env:EIDO_DIRECTORY_PICKER_PROMPT
  $dialog.ShowNewFolderButton = $true
  if ($env:EIDO_DIRECTORY_PICKER_INITIAL -and
      [System.IO.Directory]::Exists($env:EIDO_DIRECTORY_PICKER_INITIAL)) {
    $dialog.SelectedPath = $env:EIDO_DIRECTORY_PICKER_INITIAL
  }
  if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {
    [Console]::Out.Write($dialog.SelectedPath)
  }
} finally {
  $dialog.Dispose()
}`

func windowsPowerShellEncodedCommand(script string) string {
	encoded := utf16.Encode([]rune(script))
	bytes := make([]byte, len(encoded)*2)
	for index, value := range encoded {
		bytes[index*2] = byte(value)
		bytes[index*2+1] = byte(value >> 8)
	}
	return base64.StdEncoding.EncodeToString(bytes)
}

func replaceWindowsEnvironment(environment []string, values map[string]string) []string {
	result := make([]string, 0, len(environment)+len(values))
	for _, item := range environment {
		name, _, found := strings.Cut(item, "=")
		if found {
			remove := false
			for target := range values {
				if strings.EqualFold(name, target) {
					remove = true
					break
				}
			}
			if remove {
				continue
			}
		}
		result = append(result, item)
	}
	for name, value := range values {
		result = append(result, name+"="+value)
	}
	return result
}

func selectDirectory(ctx context.Context, initial, prompt string) (string, bool, error) {
	powerShell, err := exec.LookPath("powershell.exe")
	if err != nil {
		return "", false, errors.New("Windows PowerShell is required to open the directory selector")
	}
	command := exec.CommandContext(
		ctx,
		powerShell,
		"-NoLogo", "-NoProfile", "-NonInteractive", "-STA",
		"-EncodedCommand", windowsPowerShellEncodedCommand(windowsDirectoryPickerScript),
	)
	command.Env = replaceWindowsEnvironment(os.Environ(), map[string]string{
		"EIDO_DIRECTORY_PICKER_INITIAL": initial,
		"EIDO_DIRECTORY_PICKER_PROMPT":  prompt,
	})
	command.SysProcAttr = &syscall.SysProcAttr{HideWindow: true}
	output, err := command.Output()
	if err != nil {
		return "", false, errors.New("the Windows directory selector could not be opened")
	}
	selected := strings.TrimSpace(string(output))
	return selected, selected != "", nil
}
