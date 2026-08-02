//go:build windows

package launcher

import (
	"encoding/base64"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"unicode/utf16"
)

func TestWindowsDirectoryNamesRejectReservedAndInvalidNames(t *testing.T) {
	for _, name := range []string{
		`..\escape`, "CON", "con.txt", "AUX", "COM1", "LPT9.log", "trailing.", "bad:name", "bad|name",
	} {
		if validDirectoryName(name) {
			t.Errorf("expected Windows directory name %q to be rejected", name)
		}
	}
	for _, name := range []string{"research", "COM10", "报告 2026"} {
		if !validDirectoryName(name) {
			t.Errorf("expected Windows directory name %q to be accepted", name)
		}
	}
}

func TestWindowsExecutableFileRequiresExeExtension(t *testing.T) {
	directory := t.TempDir()
	executable := filepath.Join(directory, "opencode.exe")
	commandScript := filepath.Join(directory, "opencode.cmd")
	if err := os.WriteFile(executable, []byte("fixture"), 0600); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(commandScript, []byte("fixture"), 0600); err != nil {
		t.Fatal(err)
	}
	executableInfo, err := os.Stat(executable)
	if err != nil {
		t.Fatal(err)
	}
	commandScriptInfo, err := os.Stat(commandScript)
	if err != nil {
		t.Fatal(err)
	}
	if !isExecutableFile(executable, executableInfo) {
		t.Fatal("expected .exe file to be accepted")
	}
	if isExecutableFile(commandScript, commandScriptInfo) {
		t.Fatal("expected command script to be rejected")
	}
}

func TestNpmOpenCodeCandidatesResolveNativeExecutables(t *testing.T) {
	root := filepath.Join(`C:\Users\developer`, "AppData", "Roaming", "npm")
	candidates := npmOpenCodeCandidates(root)
	if len(candidates) != 3 {
		t.Fatalf("npmOpenCodeCandidates returned %d candidates, want 3", len(candidates))
	}
	for _, candidate := range candidates {
		if !strings.HasPrefix(candidate, root) || !strings.EqualFold(filepath.Ext(candidate), ".exe") {
			t.Fatalf("unexpected npm OpenCode candidate: %q", candidate)
		}
	}
	if !strings.Contains(strings.Join(candidates, "\n"), `node_modules\opencode-ai\node_modules\opencode-windows-`) {
		t.Fatalf("npm native package candidate is missing: %#v", candidates)
	}
}

func TestWindowsEnvironmentReplacementIsCaseInsensitive(t *testing.T) {
	environment := replaceWindowsEnvironment([]string{
		"Path=C:\\Windows", "opencode_server_password=inherited", "KEEP=value",
	}, map[string]string{
		"OPENCODE_SERVER_PASSWORD": "requested",
	})
	joined := strings.Join(environment, "\n")
	if strings.Contains(joined, "inherited") || !strings.Contains(joined, "KEEP=value") ||
		strings.Count(joined, "OPENCODE_SERVER_PASSWORD=requested") != 1 {
		t.Fatalf("unexpected replaced environment: %q", joined)
	}
}

func TestWindowsPowerShellCommandUsesUtf16LE(t *testing.T) {
	script := "Write-Output '选择文件夹'"
	bytes, err := base64.StdEncoding.DecodeString(windowsPowerShellEncodedCommand(script))
	if err != nil {
		t.Fatal(err)
	}
	if len(bytes)%2 != 0 {
		t.Fatalf("encoded PowerShell command has odd byte length: %d", len(bytes))
	}
	encoded := make([]uint16, len(bytes)/2)
	for index := range encoded {
		encoded[index] = uint16(bytes[index*2]) | uint16(bytes[index*2+1])<<8
	}
	if decoded := string(utf16.Decode(encoded)); decoded != script {
		t.Fatalf("decoded PowerShell command = %q, want %q", decoded, script)
	}
}

func TestInstallerExtensionOriginsValidateAndDeduplicateIDs(t *testing.T) {
	origins, err := installerExtensionOrigins(
		"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa,bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb,aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
	)
	if err != nil {
		t.Fatal(err)
	}
	if len(origins) != 2 || origins[0] != "chrome-extension://aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/" ||
		origins[1] != "chrome-extension://bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb/" {
		t.Fatalf("unexpected installer origins: %#v", origins)
	}
	for _, invalid := range []string{"", "short", "zzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz"} {
		if _, err := installerExtensionOrigins(invalid); err == nil {
			t.Fatalf("expected installer extension IDs %q to be rejected", invalid)
		}
	}
}
