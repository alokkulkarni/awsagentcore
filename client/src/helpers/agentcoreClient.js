import { fetchAuthSession } from '@aws-amplify/auth';
import { SignatureV4 } from '@smithy/signature-v4';
import { Sha256 } from '@aws-crypto/sha256-js';

/**
 * Get temporary AWS credentials from Cognito Identity Pool via Amplify.
 * @returns {Promise<{accessKeyId: string, secretAccessKey: string, sessionToken?: string}>}
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

