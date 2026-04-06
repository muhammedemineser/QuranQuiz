export function buildSeedRequests(existingUsers, seedUsers) {
  const existingUsernames = new Set(
    existingUsers
      .map((user) => String(user.username || '').trim().toLowerCase())
      .filter(Boolean)
  );

  return seedUsers.filter((seed) => {
    const username = String(seed.username || '').trim().toLowerCase();
    if (!username) {
      return false;
    }
    return !existingUsernames.has(username);
  });
}

export async function seedUsersIfEmpty(apiUrl, seedUsers) {
  const readResponse = await fetch(apiUrl, { cache: 'no-store' });
  if (!readResponse.ok) {
    throw new Error('initial users fetch failed');
  }

  const existingUsers = await readResponse.json();
  const pendingSeeds = buildSeedRequests(existingUsers, seedUsers);

  if (pendingSeeds.length === 0) {
    return existingUsers;
  }

  for (const seed of pendingSeeds) {
    const createResponse = await fetch(apiUrl, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(seed),
    });
    if (!createResponse.ok) {
      throw new Error('user seed post failed');
    }
  }

  const verifyResponse = await fetch(apiUrl, { cache: 'no-store' });
  if (!verifyResponse.ok) {
    throw new Error('verification users fetch failed');
  }
  return verifyResponse.json();
}
