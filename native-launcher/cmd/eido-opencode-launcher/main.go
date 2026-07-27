package main

import (
	"context"
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
