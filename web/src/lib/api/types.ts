// Friendly names for the generated contract types. Never edit schema.d.ts; run `npm run gen:api`.
import type { components, paths } from "./schema";

type Schemas = components["schemas"];

export type Me = Schemas["Me"];
export type Conversation = Schemas["Conversation"];
export type Message = Schemas["Message"];
export type Fixture = Schemas["Fixture"];
export type TeamRef = Schemas["TeamRef"];
export type SourceRef = Schemas["SourceRef"];
export type Card = Schemas["Card"];
export type StatCard = Schemas["StatCard"];
export type OddsCard = Schemas["OddsCard"];
export type ValueCard = Schemas["ValueCard"];
export type StreamEvent = Schemas["StreamEvent"];
export type ApiErrorBody = Schemas["ApiError"];
export type ApiErrorCode = ApiErrorBody["code"];

export type NextFixtures = NonNullable<
  paths["/fixtures/next"]["get"]["responses"][200]["content"]["application/json"]["data"]
>;
export type BreakDuration =
  paths["/me/break"]["post"]["requestBody"]["content"]["application/json"]["duration"];
export type FeedbackRating =
  paths["/feedback"]["post"]["requestBody"]["content"]["application/json"]["rating"];

export const API_ERROR_CODES = [
  "unauthenticated",
  "age_not_confirmed",
  "on_break",
  "daily_limit_reached",
  "rate_limited",
  "budget_exhausted",
  "not_found",
  "invalid_input",
  "internal",
] as const satisfies readonly ApiErrorCode[];

// Fails to compile if the contract gains an error code this list is missing.
type MissingErrorCode = Exclude<ApiErrorCode, (typeof API_ERROR_CODES)[number]>;
const assertAllErrorCodesListed: MissingErrorCode extends never ? true : never = true;
void assertAllErrorCodesListed;
