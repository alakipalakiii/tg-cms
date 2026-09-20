import { handleMediaProof } from "../../website/dreary-disk/src/media-proof.mjs";
import { withVersionMetadata } from "../../website/dreary-disk/src/version-metadata.mjs";

export default {
  async fetch(request, env) {
    const proofResponse = await handleMediaProof(
      request,
      env,
      env.CF_VERSION_METADATA?.id,
    );
    if (proofResponse) return proofResponse;

    const response = await env.ASSETS.fetch(request);
    return withVersionMetadata(response, env.CF_VERSION_METADATA?.id);
  },
};
