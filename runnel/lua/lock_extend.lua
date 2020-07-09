local token = redis.call('GET', KEYS[1])
if not token then
    -- The lock expired, reacquire.
    redis.call('SET', KEYS[1], ARGV[1], 'PX', ARGV[2])
    return 1
end

if token ~= ARGV[1] then
    -- The lock is owned by someone else.
    return 0
end

redis.call('PEXPIRE', KEYS[1], ARGV[2])
return 1
