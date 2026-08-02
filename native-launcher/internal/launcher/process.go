package launcher

const DetachedOpenCodeSubcommand = "__run-opencode"

type openCodeProcessInput struct {
	Executable string
	Workspace  string
	Username   string
	Password   string
	Port       int
	LogPath    string
}
