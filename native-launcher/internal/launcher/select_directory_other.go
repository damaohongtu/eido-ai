//go:build !darwin && !windows

package launcher

import (
	"context"
	"errors"
)

func selectDirectory(context.Context, string, string) (string, bool, error) {
	return "", false, errors.New("the graphical directory selector is currently available on macOS only")
}
