# Use the official Docker Hub Ubuntu 20.04 base image
FROM google/cloud-sdk:latest

RUN apt update && apt install -y --no-install-recommends \
    python3-dev \
    python3-pip \
    build-essential \
    libmagic1
    #google-api-python-client \
    #google-cloud-logging \
    #boto3 \
    #google-cloud-cli

RUN pip install --upgrade pip

# /app is defined as the mount in the docker-compose.yaml file and should
# point to the root of the dftimewolf install
ADD . /app
WORKDIR /app

RUN pip install -e /app

# Copy the entrypoint script into the container
COPY ./docker/gcp_nopoetry/docker-entrypoint.sh /
RUN chmod a+x /docker-entrypoint.sh

# Load the entrypoint script to be run later
ENTRYPOINT ["/docker-entrypoint.sh"]
