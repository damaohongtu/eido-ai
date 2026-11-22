variable "IMAGE_REPOSITORY" {
  default = "damaohongtu"
}

variable "IMAGE_TAG" {
  default = "latest"
}

variable "BASE_TAG" {
  default = "latest"
}

variable "PYTHON_IMAGE" {
  default = "docker.1ms.run/python:3.12-slim"
}

variable "DEBIAN_MIRROR" {
  default = "https://mirrors.aliyun.com"
}

group "default" {
  targets = ["base", "gateway", "user"]
}

target "base" {
  context = "."
  dockerfile = "docker/base.Dockerfile"
  args = {
    PYTHON_IMAGE  = PYTHON_IMAGE
    DEBIAN_MIRROR = DEBIAN_MIRROR
  }
  tags = ["${IMAGE_REPOSITORY}/eido-base:${BASE_TAG}"]
}

target "runtime" {
  context = "."
  contexts = { eido-base = "target:base" }
}

target "app" {
  inherits = ["runtime"]
  dockerfile = "docker/app.Dockerfile"
  tags = ["${IMAGE_REPOSITORY}/eido:${IMAGE_TAG}"]
}

target "gateway" {
  inherits = ["runtime"]
  dockerfile = "docker/gateway.Dockerfile"
  tags = ["${IMAGE_REPOSITORY}/eido-gateway:${IMAGE_TAG}"]
}

target "user" {
  inherits = ["runtime"]
  dockerfile = "docker/user.Dockerfile"
  tags = ["${IMAGE_REPOSITORY}/eido-user:${IMAGE_TAG}"]
}
