local token = redis.call('GET', KEYS[1])
if not token or token ~= ARGV[1] then
    -- The lock expired or is owned by someone else.
    return 0
end

redis.call('DEL', KEYS[1])
return 1
