set -eux \
	&& apt-get update \
	&& apt-get upgrade -y \
	&& apt-get install -y --no-install-recommends ca-certificates build-essential wget \
	&& rm -rf /var/lib/apt/lists/* ;

pip install --no-cache-dir -r requirements.txt;