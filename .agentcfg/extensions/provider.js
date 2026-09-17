// Project-local OpenAI-compatible provider.
// Credentials come from process.env (loaded from <repo>/.env by loop/pi_call.sh).
// Never write API_KEY into this file.

export default function (pi) {
  const baseUrl = (process.env.BASE_URL || "").replace(/\/$/, "");
  const apiKey = process.env.API_KEY || "missing";
  const modelId = process.env.MODEL_NAME || "deepseek-v4-pro";

  if (!baseUrl) {
    console.warn("[reaxevolve provider] BASE_URL is empty — set it in .env");
  }

  pi.registerProvider("reaxevolve", {
    name: "reaxevolve (OpenAI-compatible)",
    baseUrl,
    api: "openai-completions",
    apiKey,
    models: [
      {
        id: modelId,
        name: modelId,
        // Declared reasoning-capable so `--thinking` reaches the wire. Left as
        // `false` the flag was a no-op: the model reasoned at its own default and
        // spent all 16384 output tokens on it, so every Explore call came back
        // finish_reason=length with an empty body and zero hypotheses.
        reasoning: true,
        input: ["text"],
        cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
        contextWindow: 128000,
        maxTokens: 32768,
        compat: {
          supportsDeveloperRole: false,
          // Measured against this endpoint: reasoning_effort is accepted but has no
          // effect (still ~46k reasoning chars, still truncated). Only the deepseek
          // toggle actually stops it, so keep effort off and drive thinking on/off.
          supportsReasoningEffort: false,
          thinkingFormat: "deepseek",
          maxTokensField: "max_tokens",
        },
      },
    ],
  });
}
