# Cask for the `skindar/listen` Homebrew tap.
# Repo layout for the tap:  homebrew-listen/Casks/listen.rb
# Install with:  brew tap skindar/listen && brew install --cask listen
cask "listen" do
  version "0.3.0"
  sha256 "3492c3833bf21a55ab22cd4c931459e8fceb9d4e3b174c5b4c8044cc6eb4507a"

  url "https://github.com/skindar/listen/releases/download/v#{version}/Listen-#{version}.dmg",
      verified: "github.com/skindar/listen/releases/download/"
  name "Listen"
  desc "Free, offline speech-to-text that never asks you for money"
  homepage "https://github.com/skindar/listen"

  # Model downloads on first run (~707 MB, one-time); the app itself is lean.
  depends_on macos: :ventura

  app "Listen.app"

  zap trash: [
    "~/.listen",
    "~/Library/Logs/listen.log",
    "~/Library/LaunchAgents/com.valentyn.listen.plist",
  ]
end