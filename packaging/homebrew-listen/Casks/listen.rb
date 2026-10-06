# Cask for the `skindar/listen` Homebrew tap.
# Repo layout for the tap:  homebrew-listen/Casks/listen.rb
# Install with:  brew tap skindar/listen && brew install --cask listen
cask "listen" do
  version "0.3.2"
  sha256 "0b5e5d73bdd84ea6beae85c8c90708fbf523d672ba1374e3133d0504cbdebc23"

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