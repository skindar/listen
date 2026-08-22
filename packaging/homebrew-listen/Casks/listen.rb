# Cask for the `valentyn/listen` Homebrew tap.
# Repo layout for the tap:  homebrew-listen/Casks/listen.rb
# Install with:  brew tap valentyn/listen && brew install --cask listen
cask "listen" do
  version "0.2.0"
  sha256 "4907f1199aa7e72cdf56e5badab72f24ed807191dc19b20bf837ca152c80b372"

  url "https://github.com/valentyn/listen/releases/download/v#{version}/Listen-#{version}.dmg",
      verified: "github.com/valentyn/listen/releases/download/"
  name "Listen"
  desc "Free, offline speech-to-text that never asks you for money"
  homepage "https://github.com/valentyn/listen"

  # Model downloads on first run (~707 MB, one-time); the app itself is lean.
  depends_on macos: :ventura

  app "Listen.app"

  zap trash: [
    "~/.listen",
    "~/Library/Logs/listen.log",
    "~/Library/LaunchAgents/com.valentyn.listen.plist",
  ]
end