package launcher

import (
	"context"
	"testing"

	"github.com/eido-ai/eido-opencode-launcher/internal/protocol"
)

type fakePlatform struct {
	launchInput LaunchInput
	createdName string
}

func (fake *fakePlatform) Detect(context.Context) (OpenCodeInfo, error) {
	return OpenCodeInfo{Executable: "/usr/local/bin/opencode", Version: "1.2.3"}, nil
}
func (fake *fakePlatform) SelectDirectory(context.Context, string) (string, bool, error) {
	return "/tmp/project", true, nil
}
func (fake *fakePlatform) CreateDirectory(_ context.Context, _ string, name string) (string, bool, error) {
	fake.createdName = name
	return "/tmp/" + name, true, nil
}
func (fake *fakePlatform) Launch(_ context.Context, input LaunchInput) (LaunchResult, error) {
	fake.launchInput = input
	return LaunchResult{Status: "started", Endpoint: "http://127.0.0.1:4096"}, nil
}

func TestHandleRejectsProtocolMismatch(t *testing.T) {
	response := App{Platform: &fakePlatform{}}.Handle(context.Background(), protocol.Request{Protocol: 2, Command: "ping"})
	result := response.(map[string]any)
	if result["code"] != "PROTOCOL_MISMATCH" {
		t.Fatalf("unexpected result: %#v", result)
	}
}

func TestLaunchFixesHostnameAndForwardsOnlyTypedFields(t *testing.T) {
	fake := &fakePlatform{}
	request := protocol.Request{
		Protocol: 1, Command: "launch", Hostname: "127.0.0.1", Workspace: "/tmp/project",
		PreferredPort: 4096, Username: "opencode", Password: "secret", AllowPortFallback: true,
	}
	response := App{Platform: fake}.Handle(context.Background(), request).(map[string]any)
	if response["ok"] != true || fake.launchInput.Workspace != "/tmp/project" || fake.launchInput.Password != "secret" {
		t.Fatalf("unexpected launch: response=%#v input=%#v", response, fake.launchInput)
	}
}

func TestLaunchRejectsNonLoopbackHostname(t *testing.T) {
	response := App{Platform: &fakePlatform{}}.Handle(context.Background(), protocol.Request{
		Protocol: 1, Command: "launch", Hostname: "0.0.0.0",
	}).(map[string]any)
	if response["code"] != "INVALID_REQUEST" {
		t.Fatalf("unexpected response: %#v", response)
	}
}

func TestCreateDirectoryForwardsName(t *testing.T) {
	fake := &fakePlatform{}
	response := App{Platform: fake}.Handle(context.Background(), protocol.Request{
		Protocol: 1, Command: "create_directory", InitialDirectory: "/tmp", DirectoryName: "research",
	}).(map[string]any)
	if response["ok"] != true || response["workspace"] != "/tmp/research" || fake.createdName != "research" {
		t.Fatalf("unexpected response: %#v", response)
	}
}
