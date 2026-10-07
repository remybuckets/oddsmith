import { setupServer } from "msw/node";

// Tests add handlers per case with server.use(); anything unhandled fails the test.
export const server = setupServer();
