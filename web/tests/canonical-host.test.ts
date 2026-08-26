/**
 * The Host header decides where a redirect points, and it is attacker-supplied.
 *
 * These exist because the first version of this rule turned
 * `Host: www.evil.example` into a 308 pointing at `https://evil.example/` -
 * this server putting its name to a redirect somewhere else, which is the shape
 * a phishing link wants.
 */

import { test, describe } from "node:test";
import assert from "node:assert/strict";

import { apexRedirectTarget, canonicalHost } from "../lib/canonical-host.ts";

const OURS = canonicalHost("https://ontrackapp.me");

describe("reading the canonical host", () => {
  test("comes from the configured origin", () => {
    assert.equal(canonicalHost("https://ontrackapp.me"), "ontrackapp.me");
    assert.equal(canonicalHost("https://ontrackapp.me/"), "ontrackapp.me");
    assert.equal(canonicalHost("http://localhost:3000"), "localhost:3000");
  });

  test("is null when there is nothing usable to read", () => {
    assert.equal(canonicalHost(undefined), null);
    assert.equal(canonicalHost(""), null);
    assert.equal(canonicalHost("not a url"), null);
  });
});

describe("where a www request is sent", () => {
  const at = (host: string | null, extra: Record<string, unknown> = {}) =>
    apexRedirectTarget({ host, pathname: "/circuits", search: "", ...extra }, OURS);

  test("our own www spelling goes to the apex", () => {
    assert.equal(at("www.ontrackapp.me"), "https://ontrackapp.me/circuits");
    assert.equal(at("WWW.ONTRACKAPP.ME"), "https://ontrackapp.me/circuits");
  });

  test("a host that is not ours is never redirected", () => {
    // The finding this whole module exists for.
    assert.equal(at("www.evil.example"), null);
    assert.equal(at("www.ontrackapp.me.evil.example"), null);
    assert.equal(at("www.attacker.co.uk"), null);
  });

  test("the apex and a missing host are left alone", () => {
    assert.equal(at("ontrackapp.me"), null);
    assert.equal(at(null), null);
    assert.equal(at(undefined as unknown as string), null);
  });

  test("nothing redirects when no canonical host is configured", () => {
    assert.equal(
      apexRedirectTarget({ host: "www.ontrackapp.me", pathname: "/" }, null),
      null,
    );
  });

  test("the path and query survive the redirect", () => {
    assert.equal(
      at("www.ontrackapp.me", { pathname: "/calendar", search: "?season=2026" }),
      "https://ontrackapp.me/calendar?season=2026",
    );
  });

  test("https unless the proxy says the hop was plain http", () => {
    assert.equal(
      at("www.ontrackapp.me", { forwardedProto: "http" }),
      "http://ontrackapp.me/circuits",
    );
    assert.equal(
      at("www.ontrackapp.me", { forwardedProto: undefined }),
      "https://ontrackapp.me/circuits",
    );
  });
});
