//go:build windows

package launcher

import (
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"syscall"
	"unsafe"
)

const (
	messageBoxYesNo        = 0x00000004
	messageBoxIconError    = 0x00000010
	messageBoxIconQuestion = 0x00000020
	messageBoxIconInfo     = 0x00000040
	messageBoxForeground   = 0x00010000
	messageBoxYes          = 6

	registrySetValue   = 0x0002
	registryWow64Key32 = 0x0200
	registryWow64Key64 = 0x0100
	registryString     = 1

	moveFileReplaceExisting = 0x00000001
	moveFileWriteThrough    = 0x00000008
)

var (
	user32DLL       = syscall.NewLazyDLL("user32.dll")
	messageBoxW     = user32DLL.NewProc("MessageBoxW")
	kernel32DLL     = syscall.NewLazyDLL("kernel32.dll")
	moveFileExW     = kernel32DLL.NewProc("MoveFileExW")
	advapi32DLL     = syscall.NewLazyDLL("advapi32.dll")
	regCreateKeyExW = advapi32DLL.NewProc("RegCreateKeyExW")
	regSetValueExW  = advapi32DLL.NewProc("RegSetValueExW")
	regCloseKey     = advapi32DLL.NewProc("RegCloseKey")
)

// InstallerExtensionIDs is set by Windows release builds through -ldflags -X.
// Values are comma-separated fixed Chrome extension IDs.
var InstallerExtensionIDs = ""

type windowsNativeHostManifest struct {
	Name           string   `json:"name"`
	Description    string   `json:"description"`
	Path           string   `json:"path"`
	Type           string   `json:"type"`
	AllowedOrigins []string `json:"allowed_origins"`
}

func showWindowsMessage(text, title string, flags uintptr) uintptr {
	textPointer, textErr := syscall.UTF16PtrFromString(text)
	titlePointer, titleErr := syscall.UTF16PtrFromString(title)
	if textErr != nil || titleErr != nil {
		return 0
	}
	result, _, _ := messageBoxW.Call(
		0,
		uintptr(unsafe.Pointer(textPointer)),
		uintptr(unsafe.Pointer(titlePointer)),
		flags|messageBoxForeground,
	)
	return result
}

func nativeMessageInputAttached() bool {
	info, err := os.Stdin.Stat()
	if err != nil {
		return false
	}
	return info.Mode()&os.ModeNamedPipe != 0 || info.Mode().IsRegular()
}

func installerExtensionOrigins(value string) ([]string, error) {
	parts := strings.FieldsFunc(value, func(character rune) bool {
		return character == ',' || character == ';' || character == '\n' || character == '\r' || character == ' '
	})
	seen := make(map[string]bool)
	origins := make([]string, 0, len(parts))
	for _, part := range parts {
		if len(part) != 32 {
			return nil, errors.New("the installer contains an invalid Chrome extension ID")
		}
		for _, character := range part {
			if character < 'a' || character > 'p' {
				return nil, errors.New("the installer contains an invalid Chrome extension ID")
			}
		}
		if !seen[part] {
			seen[part] = true
			origins = append(origins, "chrome-extension://"+part+"/")
		}
	}
	if len(origins) == 0 {
		return nil, errors.New("the installer is not authorized for a Chrome extension")
	}
	return origins, nil
}

func moveFileReplacing(source, destination string) error {
	sourcePointer, err := syscall.UTF16PtrFromString(source)
	if err != nil {
		return err
	}
	destinationPointer, err := syscall.UTF16PtrFromString(destination)
	if err != nil {
		return err
	}
	result, _, callErr := moveFileExW.Call(
		uintptr(unsafe.Pointer(sourcePointer)),
		uintptr(unsafe.Pointer(destinationPointer)),
		moveFileReplaceExisting|moveFileWriteThrough,
	)
	if result == 0 {
		if callErr != nil && callErr != syscall.Errno(0) {
			return callErr
		}
		return errors.New("MoveFileExW failed")
	}
	return nil
}

func copyExecutableAtomically(source, destination string) error {
	sourceFile, err := os.Open(source)
	if err != nil {
		return err
	}
	defer sourceFile.Close()

	temporary, err := os.CreateTemp(filepath.Dir(destination), ".eido-launcher-*.exe")
	if err != nil {
		return err
	}
	temporaryPath := temporary.Name()
	committed := false
	defer func() {
		_ = temporary.Close()
		if !committed {
			_ = os.Remove(temporaryPath)
		}
	}()
	if _, err := io.Copy(temporary, sourceFile); err != nil {
		return err
	}
	if err := temporary.Sync(); err != nil {
		return err
	}
	if err := temporary.Close(); err != nil {
		return err
	}
	if err := moveFileReplacing(temporaryPath, destination); err != nil {
		return err
	}
	committed = true
	return nil
}

func writeFileAtomically(path string, contents []byte) error {
	temporary, err := os.CreateTemp(filepath.Dir(path), ".eido-manifest-*.json")
	if err != nil {
		return err
	}
	temporaryPath := temporary.Name()
	committed := false
	defer func() {
		_ = temporary.Close()
		if !committed {
			_ = os.Remove(temporaryPath)
		}
	}()
	if _, err := temporary.Write(contents); err != nil {
		return err
	}
	if err := temporary.Sync(); err != nil {
		return err
	}
	if err := temporary.Close(); err != nil {
		return err
	}
	if err := moveFileReplacing(temporaryPath, path); err != nil {
		return err
	}
	committed = true
	return nil
}

func setRegistryDefaultStringWithView(subkey, value string, access uint32) error {
	subkeyPointer, err := syscall.UTF16PtrFromString(subkey)
	if err != nil {
		return err
	}
	var key syscall.Handle
	result, _, _ := regCreateKeyExW.Call(
		uintptr(syscall.HKEY_CURRENT_USER),
		uintptr(unsafe.Pointer(subkeyPointer)),
		0,
		0,
		0,
		uintptr(access),
		0,
		uintptr(unsafe.Pointer(&key)),
		0,
	)
	if result != 0 {
		return syscall.Errno(result)
	}
	defer regCloseKey.Call(uintptr(key))

	data, err := syscall.UTF16FromString(value)
	if err != nil {
		return err
	}
	result, _, _ = regSetValueExW.Call(
		uintptr(key),
		0,
		0,
		registryString,
		uintptr(unsafe.Pointer(&data[0])),
		uintptr(len(data)*2),
	)
	runtime.KeepAlive(data)
	if result != 0 {
		return syscall.Errno(result)
	}
	return nil
}

func registerWindowsNativeHost(manifestPath string) error {
	const subkey = `Software\Google\Chrome\NativeMessagingHosts\ai.eido.opencode_launcher`
	var errorsByView []string
	succeeded := false
	for _, view := range []uint32{registryWow64Key32, registryWow64Key64} {
		if err := setRegistryDefaultStringWithView(subkey, manifestPath, registrySetValue|view); err != nil {
			errorsByView = append(errorsByView, err.Error())
			continue
		}
		succeeded = true
	}
	if !succeeded {
		return fmt.Errorf("could not register the Chrome Native Messaging host: %s", strings.Join(errorsByView, "; "))
	}
	return nil
}

func installWindowsLauncher() (string, error) {
	origins, err := installerExtensionOrigins(InstallerExtensionIDs)
	if err != nil {
		return "", err
	}
	localAppData := os.Getenv("LOCALAPPDATA")
	if localAppData == "" {
		return "", errors.New("LOCALAPPDATA is not available")
	}
	installRoot := filepath.Join(localAppData, "Eido")
	binDirectory := filepath.Join(installRoot, "bin")
	if err := os.MkdirAll(binDirectory, 0700); err != nil {
		return "", err
	}
	if err := os.MkdirAll(filepath.Join(installRoot, "logs"), 0700); err != nil {
		return "", err
	}

	source, err := os.Executable()
	if err != nil {
		return "", err
	}
	source, err = filepath.Abs(source)
	if err != nil {
		return "", err
	}
	destination := filepath.Join(binDirectory, "eido-opencode-launcher.exe")
	if !strings.EqualFold(filepath.Clean(source), filepath.Clean(destination)) {
		if err := copyExecutableAtomically(source, destination); err != nil {
			return "", fmt.Errorf("could not install launcher executable: %w", err)
		}
	}

	manifest := windowsNativeHostManifest{
		Name:           "ai.eido.opencode_launcher",
		Description:    "Launch OpenCode for authorized Chrome extensions",
		Path:           destination,
		Type:           "stdio",
		AllowedOrigins: origins,
	}
	contents, err := json.MarshalIndent(manifest, "", "  ")
	if err != nil {
		return "", err
	}
	contents = append(contents, '\n')
	manifestPath := filepath.Join(installRoot, "ai.eido.opencode_launcher.json")
	if err := writeFileAtomically(manifestPath, contents); err != nil {
		return "", fmt.Errorf("could not write Native Messaging manifest: %w", err)
	}
	if err := registerWindowsNativeHost(manifestPath); err != nil {
		return "", err
	}
	return installRoot, nil
}

// RunInteractiveInstallerIfNeeded turns the Windows launcher into a graphical,
// per-user installer when it is opened directly. Chrome always supplies an
// extension-origin argument and protocol stdin, so Native Messaging requests
// continue through the normal main path.
func RunInteractiveInstallerIfNeeded(arguments []string) bool {
	if len(arguments) != 1 || nativeMessageInputAttached() {
		return false
	}
	localAppData := os.Getenv("LOCALAPPDATA")
	installLocation := filepath.Join(localAppData, "Eido")
	question := "Eido OpenCode Launcher 安装程序\n\n" +
		"将为当前 Windows 用户安装本机启动组件，并注册到 Chrome。\n" +
		"不需要管理员权限。\n\n" +
		"安装位置：\n" + installLocation + "\n\n是否继续？"
	if showWindowsMessage(
		question,
		"Eido OpenCode Launcher",
		messageBoxYesNo|messageBoxIconQuestion,
	) != messageBoxYes {
		return true
	}

	installedAt, err := installWindowsLauncher()
	if err != nil {
		showWindowsMessage(
			"安装失败：\n\n"+err.Error(),
			"Eido OpenCode Launcher",
			messageBoxIconError,
		)
		return true
	}
	showWindowsMessage(
		"安装成功。\n\n安装位置：\n"+installedAt+"\n\n请完全退出并重新打开 Chrome，然后再次尝试唤起 OpenCode。",
		"Eido OpenCode Launcher",
		messageBoxIconInfo,
	)
	return true
}
