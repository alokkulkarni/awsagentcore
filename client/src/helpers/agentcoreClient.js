import { fetchAuthSession } from '@aws-amplify/auth';
import { SignatureV4 } from '@smithy/signature-v4';
import { Sha256 } from '@aws-crypto/sha256-js';

/**
 * Create a SigV4-presigned WebSocket URL for AgentCore Runtime.
 *
 * IMPORTANT: The path must use the full URL-encoded runtime ARN, NOT the short ID.
 * e.g. /runtimes/arn%3Aaws%3Abedrock-agentcore%3A.../ws
 * Using the short ID returns HTTP 403 on WebSocket upgrade.
 *
 * This mirrors the AgentCore Python SDK's generate_presigned_url() exactly:
 * - URL-encode the full ARN with encodeURIComponent
 * - Add qualifier + session ID to query params before signing
 * - Sign the https:// URL (not wss://) then convert back to wss://
 */
export async function createPresignedWebSocketUrl({ runtimeArn, region = 'eu-west-2', qualifier = 'DEFAULT', expiresIn = 300 }) {
  const session = await fetchAuthSession();
  const creds = session.credentials;

  const host = `bedrock-agentcore.${region}.amazonaws.com`;

  // Full ARN must be URL-encoded in the path (matches SDK behaviour)
  const encodedArn = encodeURIComponent(runtimeArn);
  const path = `/runtimes/${encodedArn}/ws`;

  // Build pre-signing query params (qualifier + unique session ID)
  const sessionId = crypto.randomUUID();
  const query = {
    qualifier,
    'X-Amzn-Bedrock-AgentCore-Runtime-Session-Id': sessionId,
  };

  const signer = new SignatureV4({
    credentials: {
      accessKeyId: creds.accessKeyId,
      secretAccessKey: creds.secretAccessKey,
      sessionToken: creds.sessionToken,
    },
    region,
    service: 'bedrock-agentcore',
    sha256: Sha256,
  });

  // Sign as https:// (SDK converts wss→https before signing)
  const request = {
    method: 'GET',
    hostname: host,
    path,
    query,
    headers: { host },
    protocol: 'https:',
  };

  const presigned = await signer.presign(request, { expiresIn });

  const queryString = Object.entries(presigned.query || {})
    .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v)}`)
    .join('&');

  // Return as wss:// for the browser WebSocket API
  return `wss://${host}${path}?${queryString}`;
}

/**
 * Get temporary AWS credentials from Cognito Identity Pool via Amplify.
 */
export async function getAwsCredentials() {
  const session = await fetchAuthSession();
  const creds = session.credentials;
  return {
    accessKeyId: creds.accessKeyId,
    secretAccessKey: creds.secretAccessKey,
    sessionToken: creds.sessionToken,
  };
}

/**
 * Sign an HTTP request using SigV4 with Cognito Identity Pool credentials.
 * @param {string} url - Full request URL
 * @param {RequestInit} options - fetch options (method, headers, body)
 * @param {string} region - AWS region (default: eu-west-2)
 * @param {string} service - AWS service name (default: bedrock-agentcore)
 * @returns {Promise<Response>}
 */
export async function signedFetch(url, options = {}, region = 'eu-west-2', service = 'bedrock-agentcore') {
  const creds = await getAwsCredentials();
  const urlObj = new URL(url);

  const method = (options.method || 'POST').toUpperCase();
  const body = options.body;

  const request = {
    method,
    hostname: urlObj.hostname,
    port: urlObj.port ? parseInt(urlObj.port, 10) : undefined,
    path: urlObj.pathname + urlObj.search,
    protocol: urlObj.protocol,
    headers: {
      'Content-Type': 'application/json',
      host: urlObj.hostname,
      ...(options.headers || {}),
    },
    body: body || undefined,
  };

  const signer = new SignatureV4({
    credentials: creds,
    region,
    service,
    sha256: Sha256,
  });

  const signed = await signer.sign(request);

  return fetch(url, {
    method: signed.method,
    headers: signed.headers,
    body: body || undefined,
  });
}

