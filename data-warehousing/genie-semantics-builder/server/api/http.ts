import type { Request, RequestHandler } from 'express';
import { ZodError } from 'zod';
import { StatementRejected } from '../sql/allowlist';

export class HttpError extends Error {
  constructor(
    readonly status: number,
    message: string
  ) {
    super(message);
  }
}

/** The Apps proxy sets these headers after authentication. Missing headers fail closed outside local dev. */
export function actorOf(req: Request): string {
  const actor = req.header('x-forwarded-email') ?? req.header('x-forwarded-user');
  if (actor) return actor;
  if (process.env.NODE_ENV === 'development') return 'local-dev';
  throw new HttpError(401, 'Sign in to use this app.');
}

function toHttp(err: unknown): HttpError {
  if (err instanceof HttpError) return err;
  if (err instanceof ZodError) {
    return new HttpError(
      400,
      `Invalid request: ${err.issues.map((i) => `${i.path.join('.') || 'body'} ${i.message}`).join('; ')}`
    );
  }
  if (err instanceof StatementRejected) return new HttpError(400, err.message);
  const status = (err as { statusCode?: number }).statusCode;
  if (status === 401 || status === 403) {
    // The API message names the missing privilege or scope; the client gets a generic text.
    console.warn(`Databricks API ${status}: ${(err as Error).message.slice(0, 300)}`);
    return new HttpError(403, 'Your Databricks permissions do not allow this action.');
  }
  if ((err as { code?: string }).code === '23505')
    return new HttpError(409, 'Another change happened at the same time. Try again.');
  if (err instanceof Error && err.message.startsWith('The model did not return valid')) {
    return new HttpError(502, 'The model could not produce a valid answer. Try again or rephrase the request.');
  }
  return new HttpError(500, 'Server error');
}

/** Wraps a handler so every error becomes a JSON response without internal details. */
export function handle(fn: (req: Request) => Promise<unknown>): RequestHandler {
  return (req, res) => {
    fn(req).then(
      (body) => res.json(body ?? { ok: true }),
      (err: unknown) => {
        const http = toHttp(err);
        if (http.status >= 500) console.error(err);
        res.status(http.status).json({ error: http.message });
      }
    );
  };
}
