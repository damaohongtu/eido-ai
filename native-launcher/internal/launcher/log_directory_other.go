//go:build !windows

package launcher

import (
	"os"
	"path/filepath"
)

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
