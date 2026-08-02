//go:build windows

package launcher

import (
	"errors"
	"os"
	"path/filepath"
)

func launcherLogDirectory() (string, error) {
	localAppData := os.Getenv("LOCALAPPDATA")
	if localAppData == "" {
		return "", errors.New("LOCALAPPDATA is not available")
	}
	directory := filepath.Join(localAppData, "Eido", "logs")
	if err := os.MkdirAll(directory, 0700); err != nil {
		return "", err
	}
	return directory, nil
}
