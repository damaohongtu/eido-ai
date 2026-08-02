package main

import (
	"context"
	"fmt"
	"os"
	"time"

	"github.com/eido-ai/eido-opencode-launcher/internal/launcher"
	"github.com/eido-ai/eido-opencode-launcher/internal/protocol"
)

const (
	defaultRequestTimeout   = 20 * time.Second
	directoryRequestTimeout = 5 * time.Minute
)

func requestTimeout(command string) time.Duration {
	if command == "select_directory" || command == "create_directory" {
		return directoryRequestTimeout
	}
	return defaultRequestTimeout
}

func main() {
	if launcher.RunInteractiveInstallerIfNeeded(os.Args) {
		return
	}
	if len(os.Args) == 4 && os.Args[1] == launcher.DetachedOpenCodeSubcommand {
		if err := launcher.RunDetachedOpenCodeRequest(os.Args[2], os.Args[3]); err != nil {
			_, _ = fmt.Fprintln(os.Stderr, "could not launch OpenCode:", err)
			os.Exit(1)
		}
		return
	}
	request, err := protocol.ReadRequest(os.Stdin)
	if err != nil {
		_ = protocol.WriteResponse(os.Stdout, map[string]any{
			"ok": false, "code": "INVALID_REQUEST", "message": err.Error(),
		})
		return
	}
	ctx, cancel := context.WithTimeout(context.Background(), requestTimeout(request.Command))
	defer cancel()
	response := launcher.App{Platform: launcher.SystemPlatform{}}.Handle(ctx, request)
	_ = protocol.WriteResponse(os.Stdout, response)
}
