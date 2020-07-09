benchmark:
	pytest -c /dev/null tests/performance --benchmark-sort=mean --benchmark-columns=mean,min,max,stddev,rounds
