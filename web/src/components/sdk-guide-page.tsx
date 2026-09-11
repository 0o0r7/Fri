/**
 * SdkGuidePage — step-by-step SDK onboarding guide + interactive wizard.
 * Terminal mockups are CSS-rendered. Wizard generates real Ed25519 identity
 * via Web Crypto API.
 */

import { useState } from "react";
import { Copy, Check, Download, Terminal, KeyRound, ArrowRight, Github, ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";

/* ------------------------------------------------------------------ */
/* Terminal mockup component                                           */
/* ------------------------------------------------------------------ */

function TerminalMock({
  lines,
}: {
  lines: TerminalLine[];
}) {
  return (
    <div className="overflow-x-auto rounded-lg border border-border bg-[#0d1117] p-4 font-mono text-xs leading-relaxed">
      {lines.map((line, i) => (
        <div key={i} className="flex gap-2">
          {line.type === "prompt" && (
            <span className="shrink-0 text-[#d29922]">{line.text}</span>
          )}
          {line.type === "cmd" && (
            <span className="shrink-0 text-[#3fb950]">{line.text}</span>
          )}
          {line.type === "output" && (
            <span className="shrink-0 text-[#58a6ff]">{line.text}</span>
          )}
          {line.type === "comment" && (
            <span className="shrink-0 text-[#6b7280]">{line.text}</span>
          )}
        </div>
      ))}
      <div className="mt-1 flex gap-2">
        <span className="text-[#d29922]">$</span>
        <span className="inline-block h-3.5 w-2 animate-pulse bg-[#3fb950]" />
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Copy button                                                         */
/* ------------------------------------------------------------------ */

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(text);
          setCopied(true);
          setTimeout(() => setCopied(false), 1400);
        } catch {
          /* ignore */
        }
      }}
      className="inline-flex h-8 items-center gap-1.5 rounded border border-border bg-surface px-3 font-mono text-xs text-muted transition-colors hover:border-accent hover:text-accent"
    >
      {copied ? <Check className="size-3.5 text-good" /> : <Copy className="size-3.5" />}
      {copied ? "Copied" : "Copy"}
    </button>
  );
}

/* ------------------------------------------------------------------ */
/* Step guide                                                          */
/* ------------------------------------------------------------------ */

type TerminalLine = { type: "prompt" | "cmd" | "output" | "comment"; text: string };

const STEPS: {
  num: number;
  title: string;
  desc: string;
  cmd: string;
  terminal: TerminalLine[];
}[] = [
  {
    num: 1,
    title: "Create virtual environment",
    desc: "Set up an isolated Python environment for flopkit.",
    cmd: "python -m venv flopkit-env && source flopkit-env/bin/activate",
    terminal: [
      { type: "prompt", text: "$" },
      { type: "cmd", text: "python -m venv flopkit-env" },
      { type: "prompt", text: "$" },
      { type: "cmd", text: "source flopkit-env/bin/activate" },
      { type: "output", text: "(flopkit-env) $" },
    ],
  },
  {
    num: 2,
    title: "Install flopkit",
    desc: "Install the flopkit SDK from PyPI.",
    cmd: "pip install flopkit",
    terminal: [
      { type: "prompt", text: "(flopkit-env) $" },
      { type: "cmd", text: "pip install flopkit" },
      { type: "output", text: "Collecting flopkit..." },
      { type: "output", text: "Successfully installed flopkit-0.1.0" },
    ],
  },
  {
    num: 3,
    title: "Run the wizard",
    desc: "Interactive identity creation — generates an Ed25519 keypair.",
    cmd: "flopkit wizard",
    terminal: [
      { type: "prompt", text: "(flopkit-env) $" },
      { type: "cmd", text: "flopkit wizard" },
      { type: "output", text: "Welcome to flopkit setup!" },
      { type: "output", text: "Generating Ed25519 keypair..." },
      { type: "output", text: "✓ Identity saved to identity.pem" },
      { type: "output", text: "Your DID: did:key:z6Mkqztv..." },
    ],
  },
  {
    num: 4,
    title: "View your identity",
    desc: "Display your DID and fingerprint.",
    cmd: "flopkit identity",
    terminal: [
      { type: "prompt", text: "(flopkit-env) $" },
      { type: "cmd", text: "flopkit identity" },
      { type: "output", text: "DID: did:key:z6MkqztvBh2N..." },
      { type: "output", text: "Fingerprint: 4f541151fd42c677..." },
      { type: "output", text: "Identity file: identity.pem" },
    ],
  },
  {
    num: 5,
    title: "Send your first message",
    desc: "Post a signed message to a room on technocore.chat.",
    cmd: "flopkit send 'Hello FLOP'",
    terminal: [
      { type: "prompt", text: "(flopkit-env) $" },
      { type: "cmd", text: "flopkit send 'Hello FLOP'" },
      { type: "output", text: "Signing message..." },
      { type: "output", text: "✓ Sent to room: events" },
      { type: "output", text: "  seq: 12345 · ts: 2026-09-11T..." },
    ],
  },
];

function StepGuide() {
  return (
    <div className="flex flex-col gap-6">
      {STEPS.map((step) => (
        <div key={step.num} className="flex gap-4">
          {/* Number badge */}
          <div className="flex flex-col items-center">
            <div className="flex size-9 shrink-0 items-center justify-center rounded-full bg-accent/15 font-mono text-sm font-bold text-accent">
              {step.num}
            </div>
            {step.num < STEPS.length && (
              <div className="mt-1 w-px flex-1 bg-border" />
            )}
          </div>

          {/* Content */}
          <div className="flex-1 pb-2">
            <h3 className="font-mono text-sm font-medium text-fg">
              {step.title}
            </h3>
            <p className="mt-0.5 text-sm text-muted">{step.desc}</p>
            <div className="mt-3">
              <TerminalMock lines={step.terminal} />
            </div>
            <div className="mt-2">
              <CopyButton text={step.cmd} />
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Interactive wizard                                                  */
/* ------------------------------------------------------------------ */

type WizardState = "welcome" | "generating" | "show_identity" | "download" | "done";

function InteractiveWizard() {
  const [state, setState] = useState<WizardState>("welcome");
  const [identity, setIdentity] = useState<{
    did: string;
    pem: string;
    fingerprint: string;
  } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [downloaded, setDownloaded] = useState(false);

  async function generateIdentity() {
    setState("generating");
    setError(null);
    try {
      // Generate Ed25519 keypair
      const keyPair = await crypto.subtle.generateKey("Ed25519", true, ["sign", "verify"]);

      // Export private key as PKCS8 → base64 → PEM
      const exported = await crypto.subtle.exportKey("pkcs8", keyPair.privateKey);
      const pemContent = arrayBufferToPem(exported, "PRIVATE KEY");

      // Derive DID from public key
      const pubKey = await crypto.subtle.exportKey("raw", keyPair.publicKey);
      const did = await rawKeyToDidKey(pubKey);
      const fingerprint = await sha256Fingerprint(pubKey);

      setIdentity({ did, pem: pemContent, fingerprint });
      setState("show_identity");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Key generation failed");
      setState("welcome");
    }
  }

  function downloadPem() {
    if (!identity) return;
    const blob = new Blob([identity.pem], { type: "application/x-pem-file" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "identity.pem";
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    setDownloaded(true);
    setState("download");
  }

  return (
    <div className="flop-card-lg overflow-hidden p-0">
      {/* Wizard terminal header */}
      <div className="flex items-center gap-2 border-b border-border bg-[#0d1117] px-4 py-2.5">
        <Terminal className="size-4 text-accent" />
        <span className="font-mono text-xs text-muted">flopkit wizard — interactive</span>
        <div className="ml-auto flex gap-1.5">
          <span className="size-2.5 rounded-full bg-low/60" />
          <span className="size-2.5 rounded-full bg-mid/60" />
          <span className="size-2.5 rounded-full bg-good/60" />
        </div>
      </div>

      <div className="bg-[#0d1117] p-4 font-mono text-sm">
        {state === "welcome" && (
          <div className="flex flex-col gap-3">
            <p className="text-[#58a6ff]">Welcome to the flopkit identity wizard!</p>
            <p className="text-[#6b7280]">This will generate a real Ed25519 keypair in your browser.</p>
            <p className="text-[#6b7280]">No data is sent to any server — everything stays client-side.</p>
            <button
              type="button"
              onClick={generateIdentity}
              className="mt-2 inline-flex h-9 items-center gap-2 self-start rounded bg-accent px-4 text-xs font-medium text-white transition-colors hover:bg-accent/90"
            >
              <KeyRound className="size-3.5" />
              Generate Identity
            </button>
            {error && (
              <p className="text-low text-xs">Error: {error}</p>
            )}
          </div>
        )}

        {state === "generating" && (
          <div className="flex flex-col gap-2">
            <p className="text-[#d29922]">$ flopkit wizard</p>
            <p className="text-[#58a6ff]">Generating Ed25519 keypair...</p>
            <p className="text-[#6b7280] animate-pulse">Please wait...</p>
          </div>
        )}

        {state === "show_identity" && identity && (
          <div className="flex flex-col gap-3">
            <p className="text-[#3fb950]">✓ Keypair generated successfully!</p>
            <div className="flex flex-col gap-1">
              <p className="text-[#d29922]">Your DID:</p>
              <p className="break-all text-[#58a6ff]">{identity.did}</p>
            </div>
            <div className="flex flex-col gap-1">
              <p className="text-[#d29922]">Fingerprint:</p>
              <p className="text-[#58a6ff]">{identity.fingerprint}</p>
            </div>
            <button
              type="button"
              onClick={downloadPem}
              className="mt-2 inline-flex h-9 items-center gap-2 self-start rounded bg-good/20 px-4 text-xs font-medium text-good transition-colors hover:bg-good/30"
            >
              <Download className="size-3.5" />
              Download identity.pem
            </button>
          </div>
        )}

        {state === "download" && identity && (
          <div className="flex flex-col gap-3">
            <p className="text-[#3fb950]">✓ identity.pem downloaded!</p>
            <p className="text-[#6b7280]">Store this file securely — it contains your private key.</p>
            <p className="text-[#6b7280]">Anyone with this file can sign messages as your DID.</p>
            <div className="mt-2 border-t border-border pt-3">
              <p className="text-[#d29922]">Next steps:</p>
              <ul className="mt-2 flex flex-col gap-1.5 text-[#58a6ff]">
                <li>1. Install flopkit locally: pip install flopkit</li>
                <li>2. Place identity.pem in your project directory</li>
                <li>3. Send a message: flopkit send 'Hello FLOP'</li>
              </ul>
            </div>
            <div className="mt-3 flex gap-2">
              <a
                href="https://github.com/floplabs/flopkit"
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex h-9 items-center gap-2 rounded border border-border bg-surface px-4 text-xs text-muted transition-colors hover:border-accent hover:text-accent"
              >
                <Github className="size-3.5" />
                GitHub Repo
              </a>
              <button
                type="button"
                onClick={() => {
                  setState("welcome");
                  setIdentity(null);
                  setDownloaded(false);
                }}
                className="inline-flex h-9 items-center gap-2 rounded border border-border bg-surface px-4 text-xs text-muted transition-colors hover:border-accent hover:text-accent"
              >
                Start Over
              </button>
            </div>
          </div>
        )}

        {state === "done" && (
          <div className="flex flex-col gap-2">
            <p className="text-[#3fb950]">✓ All done!</p>
            <p className="text-[#6b7280]">Your identity is ready. Check the next steps below.</p>
          </div>
        )}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Crypto helpers                                                      */
/* ------------------------------------------------------------------ */

function arrayBufferToPem(buffer: ArrayBuffer, label: string): string {
  const bytes = new Uint8Array(buffer);
  const base64 = bytesToBase64(bytes);
  const lines = base64.match(/.{1,64}/g) ?? [base64];
  return `-----BEGIN ${label}-----\n${lines.join("\n")}\n-----END ${label}-----\n`;
}

function bytesToBase64(bytes: Uint8Array): string {
  let binary = "";
  for (let i = 0; i < bytes.length; i++) {
    binary += String.fromCharCode(bytes[i]);
  }
  return btoa(binary);
}

async function rawKeyToDidKey(pubKey: ArrayBuffer): Promise<string> {
  // did:key format: did:key:z + multibase-base58btc-encoded key
  // For Ed25519, the multicodec prefix is 0xed01
  const keyBytes = new Uint8Array(pubKey);
  const prefixed = new Uint8Array(2 + keyBytes.length);
  prefixed[0] = 0xed;
  prefixed[1] = 0x01;
  prefixed.set(keyBytes, 2);
  const encoded = base58btcEncode(prefixed);
  return `did:key:z${encoded}`;
}

async function sha256Fingerprint(pubKey: ArrayBuffer): Promise<string> {
  const hash = await crypto.subtle.digest("SHA-256", pubKey);
  const bytes = new Uint8Array(hash);
  return Array.from(bytes.slice(0, 8))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

// Base58 BTC encoding (Bitcoin alphabet)
const BASE58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz";

function base58btcEncode(bytes: Uint8Array): string {
  // Count leading zeros
  let zeros = 0;
  for (let i = 0; i < bytes.length && bytes[i] === 0; i++) {
    zeros++;
  }

  // Convert to big integer string in base58
  const input = Array.from(bytes);
  const result: number[] = [];
  let start = zeros;

  while (start < input.length) {
    let remainder = 0;
    for (let i = start; i < input.length; i++) {
      const num = input[i] + remainder * 256;
      input[i] = Math.floor(num / 58);
      remainder = num % 58;
    }
    result.push(remainder);
    while (start < input.length && input[start] === 0) {
      start++;
    }
  }

  // Add leading zeros as '1's
  const encoded = "1".repeat(zeros) + result.reverse().map((n) => BASE58_ALPHABET[n]).join("");
  return encoded;
}

/* ------------------------------------------------------------------ */
/* Main page component                                                  */
/* ------------------------------------------------------------------ */

export function SdkGuidePage() {
  return (
    <div className="flex min-h-dvh flex-col bg-bg text-fg">
      <div className="pointer-events-none fixed inset-0 bg-grid" aria-hidden="true" />

      {/* Hero */}
      <section className="relative z-10 border-b border-border">
        <div className="mx-auto max-w-3xl px-4 py-8 text-center sm:px-6">
          <div className="inline-flex items-center gap-2 rounded-full bg-accent/10 px-3 py-1 font-mono text-xs text-accent">
            <Terminal className="size-3.5" />
            SDK Guide
          </div>
          <h1 className="mt-4 font-mono text-2xl font-bold tracking-tight text-balance">
            Get started with flopkit
          </h1>
          <p className="mt-2 text-sm text-pretty text-muted">
            Set up your identity and send your first signed message in 5 steps.
            Then try the interactive wizard below to generate a real Ed25519
            identity right in your browser.
          </p>
          <div className="mt-4 flex items-center justify-center gap-2">
            <a
              href="#sdk-guide"
              className="inline-flex h-9 items-center gap-2 rounded-md bg-accent px-4 text-sm font-medium text-white transition-colors hover:bg-accent/90"
            >
              Get Started
              <ArrowRight className="size-3.5" />
            </a>
            <a
              href="https://github.com/floplabs/flopkit"
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex h-9 items-center gap-2 rounded-md border border-border bg-surface px-4 text-sm text-muted transition-colors hover:border-accent hover:text-accent"
            >
              <Github className="size-3.5" />
              GitHub
            </a>
          </div>
        </div>
      </section>

      {/* Step guide */}
      <section className="relative z-10 mx-auto w-full max-w-3xl flex-1 px-4 py-8 sm:px-6">
        <h2 className="mb-6 font-mono text-lg font-bold tracking-tight text-accent">
          Step-by-step Guide
        </h2>
        <StepGuide />
      </section>

      {/* Interactive wizard */}
      <section className="relative z-10 border-t border-border">
        <div className="mx-auto max-w-3xl px-4 py-8 sm:px-6">
          <div className="mb-4 flex items-center gap-2">
            <KeyRound className="size-5 text-accent" />
            <h2 className="font-mono text-lg font-bold tracking-tight text-accent">
              Interactive Wizard
            </h2>
          </div>
          <p className="mb-4 text-sm text-muted">
            Try it right here — generate a real Ed25519 identity using the Web
            Crypto API. Your private key never leaves your browser.
          </p>
          <InteractiveWizard />

          {/* Next steps */}
          <div className="mt-8 rounded-lg border border-border bg-surface p-4">
            <h3 className="font-mono text-xs tracking-wider text-accent uppercase">
              Next Steps
            </h3>
            <ul className="mt-3 flex flex-col gap-2">
              <li className="flex items-start gap-2 text-sm text-muted">
                <ChevronRight className="mt-0.5 size-4 shrink-0 text-accent" />
                <span>
                  Install flopkit locally and place your downloaded{" "}
                  <code className="font-mono text-accent">identity.pem</code> in
                  your project directory.
                </span>
              </li>
              <li className="flex items-start gap-2 text-sm text-muted">
                <ChevronRight className="mt-0.5 size-4 shrink-0 text-accent" />
                <span>
                  Send your first signed message:{" "}
                  <code className="font-mono text-good">flopkit send 'Hello FLOP'</code>
                </span>
              </li>
              <li className="flex items-start gap-2 text-sm text-muted">
                <ChevronRight className="mt-0.5 size-4 shrink-0 text-accent" />
                <span>
                  Explore the{" "}
                  <a href="#reputation" className="text-accent hover:underline">
                    Reputation
                  </a>{" "}
                  tab to see your DID appear as FRI indexes your activity.
                </span>
              </li>
              <li className="flex items-start gap-2 text-sm text-muted">
                <ChevronRight className="mt-0.5 size-4 shrink-0 text-accent" />
                <span>
                  Check the{" "}
                  <a
                    href="https://github.com/floplabs/flopkit"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-accent hover:underline"
                  >
                    GitHub repo
                  </a>{" "}
                  for full API docs and advanced usage.
                </span>
              </li>
            </ul>
          </div>
        </div>
      </section>
    </div>
  );
}
