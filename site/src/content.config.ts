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
        // "Planned" aside for it. docs/design-plan.md's phase list decides which numbers are valid:
        // scripts/planned-pages.mjs checks the page against it and lists the page by it.
        phase: z.number().int().nonnegative().optional(),
      }),
    }),
  }),
};
