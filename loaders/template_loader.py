def read_template(file_path):
    """
    Read an email template from a text file.
    """
    with open(file_path, "r", encoding="utf-8") as file:
        return file.read()