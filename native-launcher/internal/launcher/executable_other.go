//go:build !windows

package launcher

import "os"

func isExecutableFile(_ string, info os.FileInfo) bool {
	return info.Mode().IsRegular() && info.Mode().Perm()&0111 != 0
}
