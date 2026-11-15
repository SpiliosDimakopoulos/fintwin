import puppeteer from "puppeteer-core";

// CHROME_PATH overrides the Windows default; on Linux/macOS it must be set.
const DEFAULT_CHROME = "C:/Program Files/Google/Chrome/Application/chrome.exe";

export const launch = (options = {}) =>
  puppeteer.launch({ executablePath: process.env.CHROME_PATH ?? DEFAULT_CHROME, headless: true, ...options });
