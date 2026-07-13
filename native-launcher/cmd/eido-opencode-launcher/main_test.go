package main

import (
	"testing"
	"time"
)

func TestRequestTimeoutAllowsInteractiveDirectorySelection(t *testing.T) {
	if got := requestTimeout("select_directory"); got != 5*time.Minute {
		t.Fatalf("unexpected directory timeout: %s", got)
	}
	if got := requestTimeout("launch"); got != 20*time.Second {
		t.Fatalf("unexpected launch timeout: %s", got)
	}
}
