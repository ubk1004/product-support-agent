// Liveness probe for the container. It does no work and calls no other service.
export const dynamic = "force-dynamic";

export function GET(): Response {
  return Response.json({ status: "ok" });
}
