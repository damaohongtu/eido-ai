package main

import (
	"context"
	"os"
	"time"

	"github.com/eido-ai/eido-opencode-launcher/internal/launcher"
	"github.com/eido-ai/eido-opencode-launcher/internal/protocol"
)

func main() {
	request, err := protocol.ReadRequest(os.Stdin)
	if err != nil {
		_ = protocol.WriteResponse(os.Stdout, map[string]any{
			"ok": false, "code": "INVALID_REQUEST", "message": err.Error(),
		})
		return
	}
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
	defer cancel()
	response := launcher.App{Platform: launcher.SystemPlatform{}}.Handle(ctx, request)
	_ = protocol.WriteResponse(os.Stdout, response)
}
