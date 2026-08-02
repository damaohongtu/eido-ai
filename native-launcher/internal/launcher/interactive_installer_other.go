//go:build !windows

package launcher

func RunInteractiveInstallerIfNeeded([]string) bool {
	return false
}
