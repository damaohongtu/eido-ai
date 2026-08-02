//go:build windows

package launcher

import (
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
)

func npmOpenCodeCandidates(root string) []string {
	if root == "" {
		return nil
	}
	packageArchitectures := []string{"x64", "arm64"}
	if runtime.GOARCH == "arm64" {
		packageArchitectures = []string{"arm64", "x64"}
	}
	candidates := []string{
		filepath.Join(root, "node_modules", "opencode-ai", "bin", "opencode.exe"),
	}
	for _, architecture := range packageArchitectures {
		candidates = append(candidates, filepath.Join(
			root,
			"node_modules", "opencode-ai", "node_modules",
			"opencode-windows-"+architecture, "bin", "opencode.exe",
		))
	}
	return candidates
}

func opencodeCandidates() []string {
	candidates := make([]string, 0, 8)
	if path, err := exec.LookPath("opencode.exe"); err == nil {
		candidates = append(candidates, path)
	}
	if home, err := os.UserHomeDir(); err == nil && home != "" {
		candidates = append(candidates, filepath.Join(home, ".opencode", "bin", "opencode.exe"))
	}
	if commandScript, err := exec.LookPath("opencode.cmd"); err == nil {
		candidates = append(candidates, npmOpenCodeCandidates(filepath.Dir(commandScript))...)
	}
	if appData := os.Getenv("APPDATA"); appData != "" {
		candidates = append(candidates, npmOpenCodeCandidates(filepath.Join(appData, "npm"))...)
	}
	if localAppData := os.Getenv("LOCALAPPDATA"); localAppData != "" {
		candidates = append(candidates, filepath.Join(localAppData, "Microsoft", "WinGet", "Links", "opencode.exe"))
	}
	return candidates
}
