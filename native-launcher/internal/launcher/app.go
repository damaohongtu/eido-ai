package launcher

import (
	"context"
	"fmt"
	"runtime"

	"github.com/eido-ai/eido-opencode-launcher/internal/protocol"
)

const (
	ProtocolVersion = 1
)

// LauncherVersion is replaced by the release build through -ldflags -X.
var LauncherVersion = "0.1.4-dev"

type OpenCodeInfo struct {
	Executable string
	Version    string
}

type LaunchInput struct {
	Workspace         string
	PreferredPort     int
	Username          string
	Password          string
	AllowPortFallback bool
}

type LaunchResult struct {
	Status    string
	PID       int
	Endpoint  string
	Workspace string
	Username  string
	Password  string
	Version   string
	LogPath   string
}

type Platform interface {
	Detect(context.Context) (OpenCodeInfo, error)
	SelectDirectory(context.Context, string) (string, bool, error)
	CreateDirectory(context.Context, string, string) (string, bool, error)
	Launch(context.Context, LaunchInput) (LaunchResult, error)
}

type App struct {
	Platform Platform
}

func failure(code, message string) map[string]any {
	return map[string]any{"ok": false, "code": code, "message": message}
}

func (app App) Handle(ctx context.Context, request protocol.Request) any {
	if request.Protocol != ProtocolVersion {
		return failure("PROTOCOL_MISMATCH", fmt.Sprintf("unsupported protocol version %d", request.Protocol))
	}

	switch request.Command {
	case "ping":
		return map[string]any{
			"ok": true, "protocol": ProtocolVersion, "launcherVersion": LauncherVersion,
			"platform":     runtime.GOOS + "-" + runtime.GOARCH,
			"capabilities": []string{"detect", "select_directory", "create_directory", "launch"},
		}
	case "detect":
		info, err := app.Platform.Detect(ctx)
		if err != nil {
			return failure("OPENCODE_NOT_FOUND", err.Error())
		}
		return map[string]any{
			"ok": true, "installed": true, "executable": info.Executable, "version": info.Version,
		}
	case "select_directory":
		workspace, selected, err := app.Platform.SelectDirectory(ctx, request.InitialDirectory)
		if err != nil {
			return failure("DIRECTORY_SELECTOR_FAILED", err.Error())
		}
		return map[string]any{"ok": true, "selected": selected, "workspace": workspace}
	case "create_directory":
		workspace, created, err := app.Platform.CreateDirectory(ctx, request.InitialDirectory, request.DirectoryName)
		if err != nil {
			if coded, ok := err.(CodedError); ok {
				return failure(coded.Code, coded.Message)
			}
			return failure("DIRECTORY_CREATE_FAILED", err.Error())
		}
		return map[string]any{"ok": true, "created": created, "workspace": workspace}
	case "launch":
		if request.Hostname != "127.0.0.1" {
			return failure("INVALID_REQUEST", "hostname must be 127.0.0.1")
		}
		result, err := app.Platform.Launch(ctx, LaunchInput{
			Workspace: request.Workspace, PreferredPort: request.PreferredPort,
			Username: request.Username, Password: request.Password,
			AllowPortFallback: request.AllowPortFallback,
		})
		if err != nil {
			if coded, ok := err.(CodedError); ok {
				return failure(coded.Code, coded.Message)
			}
			return failure("SPAWN_FAILED", err.Error())
		}
		return map[string]any{
			"ok": true, "status": result.Status, "pid": result.PID,
			"endpoint": result.Endpoint, "workspace": result.Workspace,
			"username": result.Username, "password": result.Password,
			"version": result.Version, "logPath": result.LogPath,
		}
	default:
		return failure("UNKNOWN_COMMAND", "unsupported launcher command")
	}
}

type CodedError struct {
	Code    string
	Message string
}

func (err CodedError) Error() string { return err.Message }
