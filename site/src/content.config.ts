import { docsLoader } from "@astrojs/starlight/loaders";
import { docsSchema } from "@astrojs/starlight/schema";
import { defineCollection } from "astro:content";
import { z } from "astro/zod";

export const collections = {
  docs: defineCollection({
    loader: docsLoader(),
    schema: docsSchema({
      extend: z.object({
        // The design-plan phase that writes this placeholder page. MarkdownContent shows the
        // "Planned" aside for it, and scripts/planned-pages.mjs checks and lists it.
        phase: z.number().int().min(0).max(7).optional(),
      }),
    }),
  }),
};
