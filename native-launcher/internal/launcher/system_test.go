package launcher

import (
	"fmt"
	"net"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestCanonicalWorkspace(t *testing.T) {
	directory := t.TempDir()
	got, err := canonicalWorkspace(directory)
	if err != nil {
		t.Fatalf("canonicalWorkspace returned error: %v", err)
	}
	if !filepath.IsAbs(got) {
		t.Fatalf("expected absolute path, got %q", got)
	}
	if _, err := canonicalWorkspace("relative/path"); err == nil {
		t.Fatal("expected relative path to be rejected")
	}
	file := filepath.Join(directory, "file.txt")
	if err := os.WriteFile(file, []byte("test"), 0600); err != nil {
		t.Fatal(err)
	}
	if _, err := canonicalWorkspace(file); err == nil {
		t.Fatal("expected regular file to be rejected")
	}
}

func TestGeneratedPasswordHasSufficientEntropy(t *testing.T) {
	password, err := generatePassword()
	if err != nil {
		t.Fatal(err)
	}
	if len(password) < 43 {
		t.Fatalf("password is unexpectedly short: %d", len(password))
	}
}

func TestCredentialRejectsEnvironmentInjection(t *testing.T) {
	if err := validateCredential("value\nINJECTED=yes", "password", 1024); err == nil {
		t.Fatal("expected newline to be rejected")
	}
	if err := validateCredential(strings.Repeat("x", 129), "username", 128); err == nil {
		t.Fatal("expected oversized username to be rejected")
	}
}

func TestChoosePortReportsOpenCodeAuthMismatch(t *testing.T) {
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	server := &http.Server{Handler: http.HandlerFunc(func(writer http.ResponseWriter, _ *http.Request) {
		writer.WriteHeader(http.StatusUnauthorized)
	})}
	go func() { _ = server.Serve(listener) }()
	t.Cleanup(func() { _ = server.Close() })

	port := listener.Addr().(*net.TCPAddr).Port
	_, _, err = choosePort(port, true, "opencode", "wrong-password")
	if err == nil || !strings.Contains(fmt.Sprint(err), "credentials do not match") {
		t.Fatalf("expected auth mismatch, got %v", err)
	}
}
