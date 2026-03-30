import { fetchAuthSession } from '@aws-amplify/auth';
import { SignatureV4 } from '@smithy/signature-v4';
import { Sha256 } from '@aws-crypto/sha256-js';
import { CognitoIdentityClient, GetIdCommand, GetOpenIdTokenCommand } from '@aws-sdk/client-cognito-identity';
import { fromWebToken } from '@aws-sdk/credential-providers';

/**
 * Get credentials via the classic Cognito authflow (GetId → GetOpenIdToken →
 * AssumeRoleWithWebIdentity). Unlike the enhanced flow used by Amplify's
 * fetchAuthSession(), the classic flow does NOT attach an internal Cognito
 * session policy, so the full IAM role policy applies — including
 * bedrock-agentcore:InvokeAgentRuntimeWithWebSocketStream.
 */
async function getCognitoClassicCredentials({ identityPoolId, region, unauthRoleArn }) {
  const cognitoClient = new CognitoIdentityClient({ region });

  const { IdentityId } = await cognitoClient.send(
    new GetIdCommand({ IdentityPoolId: identityPoolId })
  );

  const { Token } = await cognitoClient.send(
    new GetOpenIdTokenCommand({ IdentityId })
  );

  // Assume the role directly with no session policy document.
  // fromWebToken internally calls sts:AssumeRoleWithWebIdentity.
  const credProvider = fromWebToken({
    roleArn: unauthRoleArn,
    webIdentityToken: Token,
    roleSessionName: 'ARIABrowserSession',
    clientConfig: { region },
  });

  return credProvider();
}

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
 *
 * NOTE: Uses classic Cognito authflow (not enhanced) so that no Cognito-managed
 * session policy restricts the bedrock-agentcore:InvokeAgentRuntimeWithWebSocketStream action.
 */
export async function createPresignedWebSocketUrl({
  runtimeArn,
  region = 'eu-west-2',
  qualifier = 'DEFAULT',
  expiresIn = 300,
  identityPoolId,
  unauthRoleArn,
}) {
  let creds;
  if (identityPoolId && unauthRoleArn) {
    // Classic flow: no Cognito-managed session policy restrictions
    creds = await getCognitoClassicCredentials({ identityPoolId, region, unauthRoleArn });
  } else {
    // Fallback to Amplify enhanced flow
    const session = await fetchAuthSession();
    creds = session.credentials;
  }

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
 * Get temporary AWS credentials from Cognito Identity Pool.
 * Uses classic flow (GetId → GetOpenIdToken → AssumeRoleWithWebIdentity) when
 * identityPoolId + unauthRoleArn are provided, bypassing the Cognito-managed
 * session policy that blocks bedrock-agentcore actions.
 * Falls back to Amplify enhanced flow when params are omitted.
 */
export async function getAwsCredentials({ identityPoolId, region, unauthRoleArn } = {}) {
  if (identityPoolId && unauthRoleArn && region) {
    return getCognitoClassicCredentials({ identityPoolId, region, unauthRoleArn });
  }
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
 * @param {{ identityPoolId?: string, unauthRoleArn?: string }} cognitoOpts - classic flow params
 * @returns {Promise<Response>}
 */
export async function signedFetch(url, options = {}, region = 'eu-west-2', service = 'bedrock-agentcore', cognitoOpts = {}) {
  const creds = await getAwsCredentials({ region, ...cognitoOpts });
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

