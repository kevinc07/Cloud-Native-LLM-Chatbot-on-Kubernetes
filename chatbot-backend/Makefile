IMAGE_NAME=chatbot-backend
CONTAINER_NAME=chatbot-backend-dev

build:
	docker build -t $(IMAGE_NAME) .

run:
	-docker rm -f $(CONTAINER_NAME) 2>/dev/null
	docker run --env-file .env -p 8000:8000 --name $(CONTAINER_NAME) $(IMAGE_NAME)

run-detached:
	docker run --env-file .env -p 8000:8000 --name $(CONTAINER_NAME) -d $(IMAGE_NAME)

stop:
	docker stop $(CONTAINER_NAME)

rm:
	docker rm $(CONTAINER_NAME)

logs:
	docker logs $(CONTAINER_NAME)

shell:
	docker exec -it $(CONTAINER_NAME) bash

whoami:
	docker exec -it $(CONTAINER_NAME) whoami

clean:
	-docker rm -f $(CONTAINER_NAME)
	-docker rmi $(IMAGE_NAME)

.PHONY: build run run-detached stop rm logs shell whoami clean