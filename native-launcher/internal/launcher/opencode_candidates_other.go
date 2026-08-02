//go:build !windows

package launcher

import (
	"os"
	"os/exec"
	"path/filepath"
)

func opencodeCandidates() []string {
	home, _ := os.UserHomeDir()
	candidates := []string{
		filepath.Join(home, ".opencode", "bin", "opencode"),
		filepath.Join(home, ".local", "bin", "opencode"),
		"/opt/homebrew/bin/opencode",
		"/usr/local/bin/opencode",
	}
	if path, err := exec.LookPath("opencode"); err == nil {
		candidates = append([]string{path}, candidates...)
	}
	return candidates
}
