import { SignatureV4 } from '@aws-sdk/signature-v4';
import { Sha256 } from '@aws-crypto/sha256-js';

/**
 * Sign an HTTP request using AWS SigV4.
 * @param {string} url - Full request URL
 * @param {RequestInit} options - fetch options (method, headers, body)
 * @param {{ accessKeyId: string, secretAccessKey: string, sessionToken?: string }} credentials
 * @param {string} region - AWS region
 * @param {string} service - AWS service name
 * @returns {Promise<Response>}
 */
export async function signedFetch(url, options = {}, credentials, region, service = 'bedrock-agentcore') {
  const parsedUrl = new URL(url);

  const method = (options.method || 'POST').toUpperCase();
  const body = options.body;

  const headers = {
    'Content-Type': 'application/json',
    host: parsedUrl.host,
    ...(options.headers || {}),
  };

  // Build the request object expected by SignatureV4
  const request = {
    method,
    headers,
    hostname: parsedUrl.hostname,
    port: parsedUrl.port ? parseInt(parsedUrl.port, 10) : undefined,
    path: parsedUrl.pathname + parsedUrl.search,
    protocol: parsedUrl.protocol,
    body: body || undefined,
  };

  const signer = new SignatureV4({
    credentials: {
      accessKeyId: credentials.accessKeyId,
      secretAccessKey: credentials.secretAccessKey,
      sessionToken: credentials.sessionToken || undefined,
    },
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

/**
 * Send a chat request to the ARIA backend.
 * Automatically applies SigV4 signing when in AgentCore authenticated mode.
 *
 * @param {string} chatUrl - Base URL (without /invocations)
 * @param {object} payload - { message, authenticated, customer_id }
 * @param {object} config - Full connection config from useConnection
 * @returns {Promise<string>} ARIA's plain-text response
 */
export async function chatRequest(chatUrl, payload, config) {
  if (!chatUrl) {
    throw new Error('Chat URL is not configured. Please set it in Connection Settings.');
  }

  // Ensure the URL ends with /invocations
  const invokeUrl = chatUrl.endsWith('/invocations')
    ? chatUrl
    : `${chatUrl.replace(/\/$/, '')}/invocations`;

  const bodyStr = JSON.stringify(payload);

  let response;

  const useSignedRequest =
    config.authenticated &&
    config.mode === 'agentcore' &&
    config.awsAccessKeyId &&
    config.awsSecretAccessKey;

  if (useSignedRequest) {
    response = await signedFetch(
      invokeUrl,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: bodyStr,
      },
      {
        accessKeyId: config.awsAccessKeyId,
        secretAccessKey: config.awsSecretAccessKey,
        sessionToken: config.awsSessionToken || undefined,
      },
      config.awsRegion || 'us-east-1',
      'bedrock-agentcore'
    );
  } else {
    response = await fetch(invokeUrl, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: bodyStr,
    });
  }

  if (!response.ok) {
    const errText = await response.text().catch(() => '');
    throw new Error(`Server responded with ${response.status}: ${errText || response.statusText}`);
  }

  return response.text();
}
