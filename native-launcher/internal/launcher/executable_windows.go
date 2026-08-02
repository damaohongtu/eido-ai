//go:build windows

package launcher

import (
	"os"
	"path/filepath"
	"strings"
)

func isExecutableFile(path string, info os.FileInfo) bool {
	return info.Mode().IsRegular() && strings.EqualFold(filepath.Ext(path), ".exe")
}
