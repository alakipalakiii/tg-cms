import { handle } from "@astrojs/cloudflare/handler";
import { handleMediaProof } from "./media-proof.mjs";
import { withVersionMetadata } from "./version-metadata.mjs";

export default {
  async fetch(request, env, context) {
    const proofResponse = await handleMediaProof(request, env, env.CF_VERSION_METADATA?.id);
    if (proofResponse) return proofResponse;
    const response = await handle(request, env, context);
    return withVersionMetadata(response, env.CF_VERSION_METADATA?.id);
  },
};
