FROM python:3.7

WORKDIR /usr/src/lib

COPY aioevsourcing /usr/src/lib/aioevsourcing
COPY setup.py /usr/src/lib/
COPY README.md /usr/src/lib/

ARG target=.
RUN pip install -e "${target}"

COPY . /usr/src/lib/
